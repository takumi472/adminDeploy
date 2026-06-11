from app import db
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash

class User(db.Model, UserMixin):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    name = db.Column(db.String(120))
    password_hash = db.Column(db.String(128))
    role = db.Column(db.String(20), default='admin')  # 'super_admin' or 'admin'
    site_id = db.Column(db.Integer, db.ForeignKey('site.id'), nullable=True)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

class Site(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), unique=True, nullable=False)
    cloudinary_folder = db.Column(db.String(100))
    domain = db.Column(db.String(255), unique=True)
    vercel_project_id = db.Column(db.String(100))
    latest_deployment_id = db.Column(db.String(100))
    deployment_url = db.Column(db.String(255))
    
    admins = db.relationship('User', backref='site', lazy=True)