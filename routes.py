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

from sqlalchemy import text

def create_tables_on_neon(db_url):
    """
    指定されたNeon DB接続URLに対して、SQLを流し込んでテーブルを作成する
    """
    engine = create_engine(db_url)
    
    # 実行したいSQLコマンドのリスト
    sql_script = """
    CREATE TABLE IF NOT EXISTS "attachments" (
        "id" serial PRIMARY KEY,
        "filename" varchar(255) NOT NULL,
        "original_name" varchar(255) NOT NULL,
        "meeting_id" integer NOT NULL
    );
    CREATE TABLE IF NOT EXISTS "learning_records" (
        "id" serial PRIMARY KEY,
        "student_id" integer NOT NULL,
        "staff_id" integer NOT NULL,
        "lesson_date" date DEFAULT CURRENT_DATE,
        "textbook_progress" varchar(50),
        "today_learning_content" text,
        "recorded_at" timestamp DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE IF NOT EXISTS "meetings" (
        "id" serial PRIMARY KEY,
        "title" varchar(200) NOT NULL,
        "date" date NOT NULL,
        "pdf_path" varchar(255),
        "content" text NOT NULL,
        "created_by" integer
    );
    CREATE TABLE IF NOT EXISTS "staffs" (
        "id" serial PRIMARY KEY,
        "user_id" integer NOT NULL,
        "face_photo_path" varchar(255),
        "email" varchar(120) NOT NULL,
        "submission_date" date,
        "last_name_kanji" varchar(50) NOT NULL,
        "first_name_kanji" varchar(50) NOT NULL,
        "last_name_kana" varchar(50) NOT NULL,
        "first_name_kana" varchar(50) NOT NULL,
        "post_code" varchar(10) NOT NULL,
        "address" varchar(255) NOT NULL,
        "tel_main" varchar(20) NOT NULL,
        "tel_sub" varchar(20),
        "exp_jp" text,
        "exp_other" text,
        "hobbies" varchar(255),
        "skills" varchar(255),
        "qualifications" varchar(255),
        "intent" text
    );
    CREATE TABLE IF NOT EXISTS "students" (
        "id" serial PRIMARY KEY,
        "face_photo_path" varchar(255) NOT NULL,
        "name_kana" varchar(100) NOT NULL,
        "country_of_origin" varchar(50) NOT NULL,
        "native_language" varchar(50) NOT NULL,
        "other_languages" varchar(100),
        "occupation" varchar(50),
        "residential_area" varchar(50) NOT NULL,
        "jlpt_level" varchar(10) NOT NULL,
        "learning_purpose" text,
        "life_troubles" text,
        "how_knew_class" varchar(50) NOT NULL,
        "how_knew_class_other" text,
        "created_at" timestamp DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE IF NOT EXISTS "users" (
        "id" serial PRIMARY KEY,
        "username" varchar(50) NOT NULL UNIQUE,
        "password_hash" varchar(256) NOT NULL,
        "role" varchar(20) NOT NULL,
        "name" varchar(50) NOT NULL,
        "line_user_id" varchar(100) UNIQUE
    );
    """
    
    # 制約（ForeignKeyなど）は、テーブル作成後に順番に追加されるのが安全です
    fk_script = """
    ALTER TABLE "attachments" ADD CONSTRAINT IF NOT EXISTS "fk_attachment_meeting" FOREIGN KEY ("meeting_id") REFERENCES "meetings"("id");
    ALTER TABLE "learning_records" ADD CONSTRAINT IF NOT EXISTS "fk_record_staff" FOREIGN KEY ("staff_id") REFERENCES "users"("id");
    ALTER TABLE "learning_records" ADD CONSTRAINT IF NOT EXISTS "fk_record_student" FOREIGN KEY ("student_id") REFERENCES "students"("id") ON DELETE CASCADE;
    ALTER TABLE "meetings" ADD CONSTRAINT IF NOT EXISTS "fk_meeting_user" FOREIGN KEY ("created_by") REFERENCES "users"("id");
    ALTER TABLE "staffs" ADD CONSTRAINT IF NOT EXISTS "fk_staff_user" FOREIGN KEY ("user_id") REFERENCES "users"("id") ON DELETE CASCADE;
    """

    with engine.begin() as conn:
        conn.execute(text(sql_script))
        conn.execute(text(fk_script))
    
    engine.dispose()

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
    new_repo_name = f"takesato-site-{site.id}"
    current_app.logger.info(f"--- [START] サイトID {site_id} のデプロイ: {new_repo_name} ---")

    vercel_headers = {"Authorization": f"Bearer {VERCEL_TOKEN}"}
    github_headers = {"Authorization": f"Bearer {GITHUB_TOKEN}", "Accept": "application/vnd.github.v3+json"}
    neon_headers = {"Authorization": f"Bearer {NEON_API_KEY}", "Content-Type": "application/json"}

    try:
        # 0. Cloudinary フォルダ作成
        if site.cloudinary_folder:
            current_app.logger.info("Step 0: Cloudinaryフォルダ確認...")
            cloudinary_auth = (CLOUDINARY_API_KEY, CLOUDINARY_API_SECRET)
            folders = [site.cloudinary_folder, f"{site.cloudinary_folder}/staffs", 
                       f"{site.cloudinary_folder}/students", f"{site.cloudinary_folder}/takesato_meeting_attachements"]
            for path in folders:
                requests.post(f"https://api.cloudinary.com/v1_1/{CLOUDINARY_CLOUD_NAME}/folders/{path}", auth=cloudinary_auth)

        # 1. GitHub リポジトリ作成
        current_app.logger.info("Step 1: GitHub確認/作成...")
        gh_check = requests.get(f"https://api.github.com/repos/{GITHUB_USER}/{new_repo_name}", headers=github_headers)
        if gh_check.status_code == 200:
            repo_info = gh_check.json()
        else:
            gh_res = requests.post(f"https://api.github.com/repos/{GITHUB_USER}/{GIT_REPO_ID}/generate", 
                                   headers=github_headers, json={"name": new_repo_name, "owner": GITHUB_USER, "private": False})
            if gh_res.status_code not in [200, 201]: raise Exception(f"GitHub作成失敗: {gh_res.text}")
            repo_info = gh_res.json()
        full_repo_name = repo_info['full_name']
        repo_id = str(repo_info['id'])

        # 2. Neon DB作成
        current_app.logger.info("Step 2: Neon DB確認/作成...")
        neon_list = requests.get("https://console.neon.tech/api/v2/projects", headers=neon_headers).json()
        existing_project = next((p for p in neon_list.get('projects', []) if p['name'] == new_repo_name), None)
        
        if existing_project:
            neon_id = existing_project['id']
            conn_res = requests.get(f"https://console.neon.tech/api/v2/projects/{neon_id}/connection_uris", headers=neon_headers)
            new_db_url = conn_res.json()['connection_uris'][0]['connection_uri']
        else:
            neon_res = requests.post("https://console.neon.tech/api/v2/projects", headers=neon_headers, json={"project": {"name": new_repo_name}})
            if neon_res.status_code not in [200, 201]: raise Exception(f"Neon作成失敗: {neon_res.text}")
            new_db_url = neon_res.json()['connection_uris'][0]['connection_uri']
        
        if new_db_url.startswith("postgres://"): new_db_url = new_db_url.replace("postgres://", "postgresql://", 1)

        # 3. DBテーブル作成
        current_app.logger.info("Step 3: DBテーブル初期化...")
        engine = create_engine(new_db_url)
        with engine.begin() as conn:
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS "attachments" ("id" serial PRIMARY KEY, "filename" varchar(255) NOT NULL, "original_name" varchar(255) NOT NULL, "meeting_id" integer NOT NULL);
                CREATE TABLE IF NOT EXISTS "learning_records" ("id" serial PRIMARY KEY, "student_id" integer NOT NULL, "staff_id" integer NOT NULL, "lesson_date" date DEFAULT CURRENT_DATE, "textbook_progress" varchar(50), "today_learning_content" text, "recorded_at" timestamp DEFAULT CURRENT_TIMESTAMP);
                CREATE TABLE IF NOT EXISTS "meetings" ("id" serial PRIMARY KEY, "title" varchar(200) NOT NULL, "date" date NOT NULL, "pdf_path" varchar(255), "content" text NOT NULL, "created_by" integer);
                CREATE TABLE IF NOT EXISTS "staffs" ("id" serial PRIMARY KEY, "user_id" integer NOT NULL, "face_photo_path" varchar(255), "email" varchar(120) NOT NULL, "submission_date" date, "last_name_kanji" varchar(50) NOT NULL, "first_name_kanji" varchar(50) NOT NULL, "last_name_kana" varchar(50) NOT NULL, "first_name_kana" varchar(50) NOT NULL, "post_code" varchar(10) NOT NULL, "address" varchar(255) NOT NULL, "tel_main" varchar(20) NOT NULL, "tel_sub" varchar(20), "exp_jp" text, "exp_other" text, "hobbies" varchar(255), "skills" varchar(255), "qualifications" varchar(255), "intent" text);
                CREATE TABLE IF NOT EXISTS "students" ("id" serial PRIMARY KEY, "face_photo_path" varchar(255) NOT NULL, "name_kana" varchar(100) NOT NULL, "country_of_origin" varchar(50) NOT NULL, "native_language" varchar(50) NOT NULL, "other_languages" varchar(100), "occupation" varchar(50), "residential_area" varchar(50) NOT NULL, "jlpt_level" varchar(10) NOT NULL, "learning_purpose" text, "life_troubles" text, "how_knew_class" varchar(50) NOT NULL, "how_knew_class_other" text, "created_at" timestamp DEFAULT CURRENT_TIMESTAMP);
                CREATE TABLE IF NOT EXISTS "users" ("id" serial PRIMARY KEY, "username" varchar(50) NOT NULL UNIQUE, "password_hash" varchar(256) NOT NULL, "role" varchar(20) NOT NULL, "name" varchar(50) NOT NULL, "line_user_id" varchar(100) UNIQUE);
                INSERT INTO users (username, password_hash, role, name) VALUES ('admin@example.com', 'scrypt:32768:8:1$X9ncSAWmXVEo7qyM$4c7b362ab334809a0eac7e2f6a604797ee7af6b4f902f2635a0ed9bca518b5b999db859fd39e8c8373266d1c07a74e1733fffb797d6cd5a16f12cf1ad13ce5a4', 'admin', '管理者 太郎') ON CONFLICT (username) DO NOTHING;
                INSERT INTO users (username, password_hash, role, name) VALUES ('admin_2@example.com','scrypt:32768:8:1$X9ncSAWmXVEo7qyM$4c7b362ab334809a0eac7e2f6a604797ee7af6b4f902f2635a0ed9bca518b5b999db859fd39e8c8373266d1c07a74e1733fffb797d6cd5a16f12cf1ad13ce5a4', 'admin', '管理者 次郎') ON CONFLICT (username) DO NOTHING;
            """))
        engine.dispose()

        # 4. Vercel プロジェクト作成
        current_app.logger.info("Step 4: Vercelプロジェクト確認...")
        vercel_check = requests.get(f"{VERCEL_API_URL}/v9/projects/{new_repo_name}", headers=vercel_headers)
        if vercel_check.status_code == 200:
            site.vercel_project_id = vercel_check.json()['id']
        else:
            res = requests.post(f"{VERCEL_API_URL}/v9/projects", headers=vercel_headers, 
                                json={"name": new_repo_name, "framework": "flask", "gitRepository": {"type": "github", "repo": full_repo_name}})
            if res.status_code not in [200, 201]: raise Exception(f"Vercel作成失敗: {res.text}")
            site.vercel_project_id = res.json()['id']
        db.session.commit()

        # 4.5 Vercel 環境変数設定
        current_app.logger.info("Step 4.5: Vercel環境変数設定...")
        env_vars = [
            {"key": "MAIL_SERVER", "value": "smtp.gmail.com", "type": "plain", "target": ["production"]},
            {"key": "MAIL_PORT", "value": "587", "type": "plain", "target": ["production"]},
            {"key": "SECRET_KEY", "value": os.urandom(24).hex(), "type": "encrypted", "target": ["production"]},
            {"key": "DATABASE_URL", "value": new_db_url, "type": "encrypted", "target": ["production"]},
            {"key": "CLOUDINARY_CLOUD_NAME", "value": "dga0a3qkd", "type": "plain", "target": ["production"]},
            {"key": "CLOUDINARY_API_KEY", "value": "883285726535233", "type": "plain", "target": ["production"]},
            {"key": "CLOUDINARY_API_SECRET", "value": "Md9aYHDqewNBlf8PFKeONPufc5c", "type": "encrypted", "target": ["production"]},
            {"key": "CLOUDINARY_FOLDER_PREFIX", "value": site.cloudinary_folder, "type": "plain", "target": ["production"]},
            {"key": "LINE_CLIENT_ID", "value": "2010387257", "type": "plain", "target": ["production"]},
            {"key": "LINE_CLIENT_SECRET", "value": "7f3614f8c2fabd3d1c481457c5b92d6a", "type": "encrypted", "target": ["production"]},
            {"key": "SITE_ID", "value": str(site.id), "type": "plain", "target": ["production"]}
        ]
        
        existing_envs = requests.get(f"{VERCEL_API_URL}/v10/projects/{site.vercel_project_id}/env", headers=vercel_headers).json().get('envs', [])
        for env in env_vars:
            target = next((e for e in existing_envs if e['key'] == env['key']), None)
            if target:
                requests.patch(f"{VERCEL_API_URL}/v10/projects/{site.vercel_project_id}/env/{target['id']}", headers=vercel_headers, json={"value": env['value']})
            else:
                requests.post(f"{VERCEL_API_URL}/v10/projects/{site.vercel_project_id}/env", headers=vercel_headers, json=env)

        # 5. デプロイ実行
        current_app.logger.info("Step 5: デプロイトリガー実行...")
        time.sleep(2)
        deploy_data = {"name": site.name, "project": site.vercel_project_id, "gitSource": {"type": "github", "repoId": repo_id, "ref": "main"}}
        res = requests.post(f"{VERCEL_API_URL}/v13/deployments", headers=vercel_headers, json=deploy_data)
        
        if res.status_code in [200, 201]:
            deploy_info = res.json()
            site.latest_deployment_id = deploy_info.get('id')
            site.deployment_url = deploy_info.get('url')
            db.session.commit()
            current_app.logger.info(f"--- [SUCCESS] デプロイ完了: {site.deployment_url} ---")
            flash("サイトのデプロイを開始しました。", "success")
        else:
            raise Exception(f"Deployment failed: {res.text}")

    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"--- [ERROR] デプロイ失敗: {str(e)} ---")
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