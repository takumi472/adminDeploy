from security import decrypt_value

from app import db
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash


class User(db.Model, UserMixin):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    name = db.Column(db.String(120))
    password_hash = db.Column(db.String(256))
    role = db.Column(db.String(20), default="admin")  # 'super_admin' or 'admin'
    site_id = db.Column(db.Integer, db.ForeignKey("sites.id"), nullable=True)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)


class Site(db.Model):
    __tablename__ = "sites"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), unique=True, nullable=False)
    cloudinary_folder = db.Column(db.String(100))
    domain = db.Column(db.String(255), unique=True)
    vercel_project_id = db.Column(db.String(100))
    latest_deployment_id = db.Column(db.String(100))
    deployment_url = db.Column(db.String(255))

    admins = db.relationship("User", backref="site_ref", lazy=True)
    env_vars = db.relationship("SiteEnvVar", backref="site_ref", lazy=True)


class SiteEnvVar(db.Model):
    __tablename__ = "site_env_vars"

    id = db.Column(db.Integer, primary_key=True)
    site_id = db.Column(
        db.Integer, db.ForeignKey("sites.id", ondelete="CASCADE"), nullable=False
    )
    key = db.Column(db.String(100), nullable=False)
    value = db.Column(db.Text, nullable=False)
    is_secret = db.Column(db.Boolean, default=False)
    target_env = db.Column(db.String(50), default="production")

    site_id = db.Column(
        db.Integer, db.ForeignKey("sites.id", ondelete="CASCADE"), nullable=False
    )

    def to_vercel_format(self):
        """Vercel APIのJSON形式に変換するヘルパー"""
        return {
            "key": self.key,
            "value": decrypt_value(self.value) if self.is_secret else self.value,
            "type": "encrypted" if self.is_secret else "plain",
            "target": [self.target_env],
        }

    def __repr__(self):
        return f"<SiteEnvVar {self.key} for Site {self.site_id}>"


class DeploymentStatus(db.Model):
    __tablename__ = "deployment_statuses"

    id = db.Column(db.Integer, primary_key=True)
    site_id = db.Column(
        db.Integer, db.ForeignKey("sites.id", ondelete="CASCADE"), nullable=False
    )

    # ステータス詳細
    status = db.Column(
        db.String(50), nullable=False
    )  # 例: 'CLOUDINARY_IN_PROGRESS', 'SUCCESS', 'FAILED'
    step_name = db.Column(db.String(100))  # 例: 'Step 4.5'
    message = db.Column(db.Text)  # エラー時のメッセージなど

    created_at = db.Column(db.DateTime, default=db.func.now())

    def __repr__(self):
        return f"<DeploymentStatus {self.status} for Site {self.site_id}>"
