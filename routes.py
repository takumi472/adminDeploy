import os
import requests
import time
from sqlalchemy import create_engine, desc
from flask import jsonify
from flask import (
    Blueprint,
    render_template,
    request,
    redirect,
    url_for,
    flash,
    current_app,
)
from flask_login import login_required, current_user
from app import db
from app.models import Site, User, SiteEnvVar, DeploymentStatus
from app.decorators import roles_required
from security import encrypt_value

super_admin_bp = Blueprint("super_admin", __name__, url_prefix="/super-admin")

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


def save_env_var(site_id, key, value, is_secret=False):
    # 暗号化が必要な場合はここで暗号化
    # (例: Simple-crypt や cryptography ライブラリを使用)
    save_value = encrypt_value(value) if is_secret else value

    env_var = SiteEnvVar(
        site_id=site_id,
        key=key,
        value=save_value,
        is_secret=is_secret,
        target_env="production",
    )
    db.session.add(env_var)


def log_deployment_status(site_id, status, step_name=None, message=None):
    new_status = DeploymentStatus(
        site_id=site_id, status=status, step_name=step_name, message=message
    )
    db.session.add(new_status)
    db.session.commit()


@super_admin_bp.route("/sites", methods=["GET", "POST"])
@login_required
@roles_required("admin")
def manage_sites():
    if request.method == "POST":
        site_name = request.form.get("name")
        cloudinary_folder = request.form.get("cloudinary_folder")
        domain = request.form.get("domain")

        if Site.query.filter_by(name=site_name).first():
            flash("そのサイト名は既に使用されています。", "danger")
        elif domain and Site.query.filter_by(domain=domain).first():
            flash("そのドメインは既に登録されています。", "danger")
        else:
            new_site = Site(
                name=site_name, cloudinary_folder=cloudinary_folder, domain=domain
            )
            db.session.add(new_site)
            db.session.commit()

            def is_encrypted(key):
                return key in [
                    "SECRET_KEY",
                    "DATABASE_URL",
                    "CLOUDINARY_API_SECRET",
                    "LINE_CLIENT_SECRET",
                ]

            env_list = [
                ("MAIL_SERVER", "smtp.gmail.com", False),
                ("MAIL_PORT", "587", False),
                ("SECRET_KEY", os.urandom(24).hex(), True),
                ("DATABASE_URL", "", True),
                ("CLOUDINARY_CLOUD_NAME", "dga0a3qkd", False),
                ("CLOUDINARY_API_KEY", "883285726535233", False),
                ("CLOUDINARY_API_SECRET", "Md9aYHDqewNBlf8PFKeONPufc5c", True),
                ("CLOUDINARY_FOLDER_PREFIX", "", False),
                ("LINE_CLIENT_ID", "2010387257", False),
                ("LINE_CLIENT_SECRET", "7f3614f8c2fabd3d1c481457c5b92d6a", True),
                ("SITE_ID", str(new_site.id), False),
            ]

            for key, val, secret in env_list:
                save_env_var(new_site.id, key, val, secret)

            db.session.commit()
            flash(f"サイト「{site_name}」を作成しました。", "success")
            return redirect(url_for("super_admin.manage_sites"))

    sites = Site.query.all()
    return render_template("super_admin/sites.html", sites=sites)


def create_cloudinary_folders(site):
    # 0. Cloudinary フォルダ作成
    if site.cloudinary_folder:
        current_app.logger.info("Step 1: Cloudinaryフォルダ確認...")
        cloudinary_auth = (CLOUDINARY_API_KEY, CLOUDINARY_API_SECRET)
        folders = [
            site.cloudinary_folder,
            f"{site.cloudinary_folder}/staffs",
            f"{site.cloudinary_folder}/students",
            f"{site.cloudinary_folder}/takesato_meeting_attachements",
        ]
        for path in folders:
            requests.post(
                f"https://api.cloudinary.com/v1_1/{CLOUDINARY_CLOUD_NAME}/folders/{path}",
                auth=cloudinary_auth,
            )


def setup_github_repository(new_repo_name, github_headers):
    # 1. GitHub リポジトリ作成
    current_app.logger.info("Step 2: GitHub確認/作成...")
    gh_check = requests.get(
        f"https://api.github.com/repos/{GITHUB_USER}/{new_repo_name}",
        headers=github_headers,
    )
    if gh_check.status_code == 200:
        repo_info = gh_check.json()
    else:
        gh_res = requests.post(
            f"https://api.github.com/repos/{GITHUB_USER}/{GIT_REPO_ID}/generate",
            headers=github_headers,
            json={"name": new_repo_name, "owner": GITHUB_USER, "private": True},
        )
        if gh_res.status_code not in [200, 201]:
            raise Exception(f"GitHub作成失敗: {gh_res.text}")
        repo_info = gh_res.json()
    return repo_info


def setup_neon_database(neon_headers, new_repo_name):
    # 2. Neon DB作成
    current_app.logger.info("Step 3: Neon DB確認/作成...")
    neon_list = requests.get(
        "https://console.neon.tech/api/v2/projects", headers=neon_headers
    ).json()
    existing_project = next(
        (p for p in neon_list.get("projects", []) if p["name"] == new_repo_name), None
    )

    if existing_project:
        neon_id = existing_project["id"]
        conn_res = requests.get(
            f"https://console.neon.tech/api/v2/projects/{neon_id}/connection_uris",
            headers=neon_headers,
        )
        new_db_url = conn_res.json()["connection_uris"][0]["connection_uri"]
    else:
        neon_res = requests.post(
            "https://console.neon.tech/api/v2/projects",
            headers=neon_headers,
            json={"project": {"name": new_repo_name}},
        )
        if neon_res.status_code not in [200, 201]:
            raise Exception(f"Neon作成失敗: {neon_res.text}")
        new_db_url = neon_res.json()["connection_uris"][0]["connection_uri"]

    if new_db_url.startswith("postgres://"):
        new_db_url = new_db_url.replace("postgres://", "postgresql://", 1)
    return new_db_url


def initialize_db_schema(new_db_url):
    # 3. DBテーブル作成
    current_app.logger.info("Step 4: DBテーブル初期化...")
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


def setup_vercel_project(
    site, new_repo_name, new_db_url, full_repo_name, vercel_headers
):
    # プロジェクト作成と環境変数の一括設定
    # 4. Vercel プロジェクト作成
    current_app.logger.info("Step 5: Vercelプロジェクト確認...")
    vercel_check = requests.get(
        f"{VERCEL_API_URL}/v9/projects/{new_repo_name}", headers=vercel_headers
    )
    if vercel_check.status_code == 200:
        site.vercel_project_id = vercel_check.json()["id"]
    else:
        res = requests.post(
            f"{VERCEL_API_URL}/v9/projects",
            headers=vercel_headers,
            json={
                "name": new_repo_name,
                "framework": "flask",
                "gitRepository": {"type": "github", "repo": full_repo_name},
            },
        )
        if res.status_code not in [200, 201]:
            raise Exception(f"Vercel作成失敗: {res.text}")
        site.vercel_project_id = res.json()["id"]
    db.session.commit()
    # 4.5 Vercel 環境変数設定
    current_app.logger.info("Step 5.5: Vercel環境変数設定...")
    env_vars = SiteEnvVar.query.filter_by(site_id=site.id).all()

    overrides = {
        "DATABASE_URL": new_db_url,
        "CLOUDINARY_FOLDER_PREFIX": site.cloudinary_folder,
        "SITE_ID": str(site.id),
    }

    existing_envs = (
        requests.get(
            f"{VERCEL_API_URL}/v10/projects/{site.vercel_project_id}/env",
            headers=vercel_headers,
        )
        .json()
        .get("envs", [])
    )
    for env in env_vars:
        if env.key in overrides:
            # 値を上書き（シークレットなら暗号化して保存）
            new_val = overrides[env.key]
            env.value = encrypt_value(new_val) if env.is_secret else new_val
            db.session.commit()
        env_data = env.to_vercel_format()

        target = next((e for e in existing_envs if e["key"] == env_data["key"]), None)

        if target:
            requests.patch(
                f"{VERCEL_API_URL}/v10/projects/{site.vercel_project_id}/env/{target['id']}",
                headers=vercel_headers,
                json={"value": env_data["value"]},
            )
        else:
            requests.post(
                f"{VERCEL_API_URL}/v10/projects/{site.vercel_project_id}/env",
                headers=vercel_headers,
                json=env_data,
            )


def trigger_vercel_deployment(site, repo_id, vercel_headers):
    current_app.logger.info("Step 6: デプロイトリガー実行...")
    time.sleep(2)
    deploy_data = {
        "name": site.name,
        "project": site.vercel_project_id,
        "gitSource": {"type": "github", "repoId": repo_id, "ref": "main"},
    }
    res = requests.post(
        f"{VERCEL_API_URL}/v13/deployments", headers=vercel_headers, json=deploy_data
    )

    if res.status_code in [200, 201]:
        deploy_info = res.json()
        site.latest_deployment_id = deploy_info.get("id")
        site.deployment_url = deploy_info.get("url")
        db.session.commit()
        current_app.logger.info(
            f"--- [SUCCESS] デプロイ完了: {site.deployment_url} ---"
        )
        flash("サイトのデプロイを開始しました。", "success")
    else:
        raise Exception(f"Deployment failed: {res.text}")


@super_admin_bp.route("/sites/<int:site_id>/deploy", methods=["POST"])
@login_required
@roles_required("super_admin")
def deploy_site(site_id):
    site = Site.query.get_or_404(site_id)
    new_repo_name = f"{site.name}"
    current_app.logger.info(
        f"--- [START] サイトID {site_id} のデプロイ: {new_repo_name} ---"
    )

    vercel_headers = {"Authorization": f"Bearer {VERCEL_TOKEN}"}
    github_headers = {
        "Authorization": f"Bearer {GITHUB_TOKEN}",
        "Accept": "application/vnd.github.v3+json",
    }
    neon_headers = {
        "Authorization": f"Bearer {NEON_API_KEY}",
        "Content-Type": "application/json",
    }

    try:
        # 0. Cloudinary ...
        log_deployment_status(
            site_id, "Cloudinary", "Step 1", "Cloudinaryフォルダ作成開始"
        )
        create_cloudinary_folders(site)
        log_deployment_status(
            site_id, "Cloudinary", "Step 1", "Cloudinaryフォルダ作成終了"
        )

        log_deployment_status(site_id, "GitHub", "Step 2", "GitHub確認/作成開始")
        # 1. GitHub
        repo = setup_github_repository(new_repo_name, github_headers)
        log_deployment_status(site_id, "GitHub", "Step 2", "GitHub確認/作成終了")

        log_deployment_status(site_id, "Neon", "Step 3", "Neon DB確認/作成開始")
        # 2. Neon
        db_url = setup_neon_database(neon_headers, new_repo_name)
        log_deployment_status(site_id, "Neon", "Step 3", "Neon DB確認/作成終了")

        log_deployment_status(site_id, "DB Init", "Step 4", "DBテーブル初期化開始")
        # 3. DB Init
        initialize_db_schema(db_url)
        log_deployment_status(site_id, "DB Init", "Step 4", "DBテーブル初期化終了")

        log_deployment_status(site_id, "Vercel", "Step 5", "Vercelプロジェクト確認開始")
        # 4. Vercel
        setup_vercel_project(
            site, new_repo_name, db_url, repo["full_name"], vercel_headers
        )
        log_deployment_status(site_id, "Vercel", "Step 5", "Vercelプロジェクト確認終了")

        log_deployment_status(
            site_id, "デプロイ中", "Step 6", "デプロイトリガー実行開始"
        )
        # 5. Trigger
        trigger_vercel_deployment(site, str(repo["id"]), vercel_headers)
        log_deployment_status(
            site_id, "デプロイ完了", "Step 6", "デプロイトリガー実行終了"
        )

        flash("デプロイを開始しました。", "success")
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"デプロイ失敗: {str(e)}")
        flash(f"エラー: {str(e)}", "danger")

    return redirect(url_for("super_admin.manage_sites"))


def get_latest_status(site_id):
    # DeploymentStatusは同じファイルか、別ファイルからインポートして使用
    return (
        DeploymentStatus.query.filter_by(site_id=site_id)
        .order_by(desc(DeploymentStatus.created_at))
        .first()
    )


@super_admin_bp.route("/sites/deployment-statuses")
@login_required
@roles_required("admin")
def get_deploy_status():
    sites = Site.query.all()
    statuses = {
        site.id: {
            "status": (
                get_latest_status(site.id).status
                if get_latest_status(site.id)
                else "未実施"
            ),
            "step": (
                get_latest_status(site.id).step_name
                if get_latest_status(site.id)
                else ""
            ),
        }
        for site in sites
    }
    return jsonify(statuses)
    # if not site.latest_deployment_id:
    #     return jsonify({"status": "NOT_STARTED"})
    # res = requests.get(f"{VERCEL_API_URL}/v13/deployments/{site.latest_deployment_id}", headers={"Authorization": f"Bearer {VERCEL_TOKEN}"})
    # if res.status_code == 200:
    #     data = res.json()
    #     return jsonify({"status": data.get('readyState'), "url": data.get('url')})
    # return jsonify({"status": "UNKNOWN"}), 400


@super_admin_bp.route("/sites/<int:site_id>/logs")
@login_required
@roles_required("admin")
def get_deploy_logs(site_id):
    site = Site.query.get_or_404(site_id)
    if not site.latest_deployment_id:
        return jsonify({"logs": "デプロイ ID が見つかりません。"}), 404
    res = requests.get(
        f"{VERCEL_API_URL}/v2/deployments/{site.latest_deployment_id}/events",
        headers={"Authorization": f"Bearer {VERCEL_TOKEN}"},
    )
    if res.status_code == 200:
        events = res.json()
        log_text = "\n".join(
            [e.get("text", "") for e in events if e.get("type") in ["stdout", "stderr"]]
        )
        return jsonify({"logs": log_text or "ログ出力はありません。"})
    return jsonify({"logs": "Vercel からログを取得できませんでした。"}), 400


@super_admin_bp.route("/users", methods=["GET", "POST"])
@login_required
@roles_required("super_admin")
def manage_admins():
    if request.method == "POST":
        username = request.form.get("username")
        password = request.form.get("password")
        # ここで空文字なら None に強制変換する
        raw_site_id = request.form.get("site_id")
        site_id = int(raw_site_id) if raw_site_id and raw_site_id.isdigit() else None

        name = request.form.get("name")

        if User.query.filter_by(username=username).first():
            flash("そのユーザー名は既に使用されています。", "danger")
        else:
            # site_id は None または 整数であることが確定しているのでシンプルに書ける
            new_user = User(username=username, name=name, role="admin", site_id=site_id)
            new_user.set_password(password)
            db.session.add(new_user)
            db.session.commit()
            flash(f"サイト管理者を登録しました: {username}", "success")
            return redirect(url_for("super_admin.manage_admins"))

    users = User.query.filter(User.role != "super_admin").all()
    sites = Site.query.all()
    return render_template("super_admin/users.html", users=users, sites=sites)
