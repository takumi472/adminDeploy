import os
import requests
import time
from sqlalchemy import create_engine
from flask import jsonify
from flask import Blueprint, render_template, request, redirect, url_for, flash, current_app
from flask_login import login_required, current_user
from app import db
from app.models import Site, User
from app.decorators import roles_required

super_admin_bp = Blueprint('super_admin', __name__, url_prefix='/super-admin')

VERCEL_API_URL = "https://api.vercel.com"
VERCEL_TOKEN = os.environ.get("VERCEL_TOKEN")
GIT_REPO_ID = os.environ.get("GIT_REPO_ID")
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN")
GITHUB_USER = os.environ.get("GITHUB_USER")
NEON_API_KEY = os.environ.get("NEON_API_KEY")
CLOUDINARY_CLOUD_NAME = os.environ.get("CLOUDINARY_CLOUD_NAME")
CLOUDINARY_API_KEY = os.environ.get("CLOUDINARY_API_KEY")
CLOUDINARY_API_SECRET = os.environ.get("CLOUDINARY_API_SECRET")

@super_admin_bp.route('/sites', methods=['GET', 'POST'])
@login_required
@roles_required('super_admin')
def manage_sites():
    if request.method == 'POST':
        site_name = request.form.get('name')
        cloudinary_folder = request.form.get('cloudinary_folder')
        domain = request.form.get('domain')
        
        if Site.query.filter_by(name=site_name).first():
            flash('そのサイト名は既に使用されています。', 'danger')
        elif domain and Site.query.filter_by(domain=domain).first():
            flash('そのドメインは既に登録されています。', 'danger')
        else:
            new_site = Site(name=site_name, cloudinary_folder=cloudinary_folder, domain=domain)
            db.session.add(new_site)
            db.session.commit()
            flash(f'サイト「{site_name}」を作成しました。', 'success')
            return redirect(url_for('super_admin.manage_sites'))

    sites = Site.query.all()
    return render_template('super_admin/sites.html', sites=sites)

@super_admin_bp.route('/sites/<int:site_id>/deploy', methods=['POST'])
@login_required
@roles_required('super_admin')
def deploy_site(site_id):
    site = Site.query.get_or_404(site_id)
    vercel_headers = {"Authorization": f"Bearer {VERCEL_TOKEN}"}
    github_headers = {
        "Authorization": f"Bearer {GITHUB_TOKEN}",
        "Accept": "application/vnd.github.v3+json"
    }
    neon_headers = {
        "Authorization": f"Bearer {NEON_API_KEY}",
        "Content-Type": "application/json"
    }

    try:
        # 0. Cloudinary フォルダの作成
        if site.cloudinary_folder:
            cloudinary_auth = (CLOUDINARY_API_KEY, CLOUDINARY_API_SECRET)
            # 作成するフォルダのリスト（親フォルダとサブフォルダ）
            folders = [
                site.cloudinary_folder,
                f"{site.cloudinary_folder}/staffs",
                f"{site.cloudinary_folder}/students",
                f"{site.cloudinary_folder}/takesato_meeting_attachements"
            ]
            for folder_path in folders:
                requests.post(
                    f"https://api.cloudinary.com/v1_1/{CLOUDINARY_CLOUD_NAME}/folders/{folder_path}",
                    auth=cloudinary_auth
                )

        # 1. GitHubリポジトリの作成 (Templateから生成)
        new_repo_name = f"takesato-site-{site.id}"
        template_repo = f"{GITHUB_USER}/{GIT_REPO_ID}"
        
        gen_payload = {
            "name": new_repo_name,
            "owner": GITHUB_USER,
            "private": False,
            "description": f"Auto-generated repo for {site.name}"
        }
        
        # デバッグ用ログ出力
        print(f"DEBUG: Requesting URL: https://api.github.com/repos/{template_repo}/generate")
        print(f"DEBUG: GITHUB_USER: {GITHUB_USER}")
        print(f"DEBUG: GIT_REPO_ID: {GIT_REPO_ID}")
  
        gh_res = requests.post(
            f"https://api.github.com/repos/{template_repo}/generate",
            headers=github_headers,
            json=gen_payload
        )
        
        if gh_res.status_code not in [200, 201]:
            raise Exception(f"GitHubリポジトリ作成失敗({gh_res.status_code}): {gh_res.text}")
            
        full_repo_name = gh_res.json()['full_name']

        # 2. Neonで新しいプロジェクト(DB)を作成
        neon_res = requests.post(
            "https://console.neon.tech/api/v2/projects",
            headers=neon_headers,
            json={"project": {"name": new_repo_name}}
        )
        if neon_res.status_code not in [200, 201]:
            raise Exception(f"Neon Project creation failed: {neon_res.text}")
        
        neon_data = neon_res.json()
        # 接続文字列の取得 (通常最初のconnection_uriを使用)
        new_db_url = neon_data['connection_uris'][0]['connection_uri']
        if new_db_url.startswith("postgres://"):
            new_db_url = new_db_url.replace("postgres://", "postgresql://", 1)

        # 3. 新しいDBにテーブルを作成
        temp_engine = create_engine(new_db_url)
        db.metadata.create_all(bind=temp_engine)
        temp_engine.dispose()

        # 4. Vercelプロジェクトの作成
        project_data = {
            "name": f"takesato-site-{site.id}",
            "framework": "flask",
            "gitRepository": {"type": "github", "repo": full_repo_name}
        }
        res = requests.post(f"{VERCEL_API_URL}/v9/projects", headers=vercel_headers, json=project_data)
        if res.status_code not in [200, 201]:
            raise Exception(f"Project creation failed: {res.text}")
        
        project_info = res.json()
        site.vercel_project_id = project_info['id']

        if site.domain:
            requests.post(f"{VERCEL_API_URL}/v9/projects/{site.vercel_project_id}/domains", headers=vercel_headers, json={"name": site.domain})

        env_vars = [
            {"key": "DATABASE_URL", "value": new_db_url, "type": "encrypted", "target": ["production"]},
            {"key": "SECRET_KEY", "value": os.urandom(24).hex(), "type": "encrypted", "target": ["production"]},
            {"key": "SITE_ID", "value": str(site.id), "type": "plain", "target": ["production"]}
        ]
        for env in env_vars:
            requests.post(f"{VERCEL_API_URL}/v10/projects/{site.vercel_project_id}/env", headers=vercel_headers, json=env)

        # 5. Vercelデプロイの実行
        deploy_data = {
            "name": site.name,
            "project": site.vercel_project_id,
            "gitSource": {"type": "github", "repoId": str(gh_res.json()['id']), "ref": "main"}
        }
        
        # GitHubの複製が完了するまで少し待機が必要な場合がある
        time.sleep(5)
        
        res = requests.post(f"{VERCEL_API_URL}/v13/deployments", headers=vercel_headers, json=deploy_data)
        if res.status_code in [200, 201]:
            deploy_info = res.json()
            site.latest_deployment_id = deploy_info.get('id')
            site.deployment_url = deploy_info.get('url')
            db.session.commit()
            flash(f"サイト「{site.name}」のデプロイを開始しました。", "success")
        else:
            raise Exception(f"Deployment trigger failed: {res.text}")
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Vercel Deployment Error: {str(e)}")
        flash(f"デプロイエラー: {str(e)}", "danger")
    return redirect(url_for('super_admin.manage_sites'))

@super_admin_bp.route('/sites/<int:site_id>/status')
@login_required
@roles_required('super_admin')
def get_deploy_status(site_id):
    site = Site.query.get_or_404(site_id)
    if not site.latest_deployment_id:
        return jsonify({"status": "NOT_STARTED"})
    res = requests.get(f"{VERCEL_API_URL}/v13/deployments/{site.latest_deployment_id}", headers={"Authorization": f"Bearer {VERCEL_TOKEN}"})
    if res.status_code == 200:
        data = res.json()
        return jsonify({"status": data.get('readyState'), "url": data.get('url')})
    return jsonify({"status": "UNKNOWN"}), 400

@super_admin_bp.route('/sites/<int:site_id>/logs')
@login_required
@roles_required('super_admin')
def get_deploy_logs(site_id):
    site = Site.query.get_or_404(site_id)
    if not site.latest_deployment_id:
        return jsonify({"logs": "デプロイ ID が見つかりません。"}), 404
    res = requests.get(f"{VERCEL_API_URL}/v2/deployments/{site.latest_deployment_id}/events", headers={"Authorization": f"Bearer {VERCEL_TOKEN}"})
    if res.status_code == 200:
        events = res.json()
        log_text = "\n".join([e.get('text', '') for e in events if e.get('type') in ['stdout', 'stderr']])
        return jsonify({"logs": log_text or "ログ出力はありません。"})
    return jsonify({"logs": "Vercel からログを取得できませんでした。"}), 400

@super_admin_bp.route('/users', methods=['GET', 'POST'])
@login_required
@roles_required('super_admin')
def manage_admins():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        site_id = request.form.get('site_id')
        name = request.form.get('name')
        if User.query.filter_by(username=username).first():
            flash('そのユーザー名は既に使用されています。', 'danger')
        else:
            new_user = User(username=username, name=name, role='admin', site_id=site_id)
            new_user.set_password(password)
            db.session.add(new_user)
            db.session.commit()
            flash(f'サイト管理者を登録しました: {username}', 'success')
            return redirect(url_for('super_admin.manage_admins'))
    users = User.query.filter(User.role != 'super_admin').all()
    sites = Site.query.all()
    return render_template('super_admin/users.html', users=users, sites=sites)