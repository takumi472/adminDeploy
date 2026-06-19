from app import db, login_manager
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime


@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))


class User(db.Model, UserMixin):
    """
    スタッフおよびアドミンのアカウント管理用テーブル（生徒は含まない）
    """

    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(
        db.String(50), unique=True, nullable=False
    )  # ログインID（メールアドレス）
    password_hash = db.Column(db.String(256), nullable=False)  # ハッシュ化パスワード
    role = db.Column(db.String(20), nullable=False)  # 'admin' または 'staff'
    name = db.Column(db.String(50), nullable=False)  # 氏名

    # スタッフが記入した学習記録（1対多）
    # ※LearningRecord側の 'writer_staff' バックレフと自動接続されます
    records_written = db.relationship(
        "LearningRecord", backref="writer_staff", foreign_keys="LearningRecord.staff_id"
    )
    staff_profile = db.relationship(
        "Staff", backref="user", uselist=False, cascade="all, delete-orphan"
    )

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)


class Staff(db.Model):
    __tablename__ = "staffs"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(
        db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    face_photo_path = db.Column(db.String(255), nullable=True)

    # プロフィール詳細項目
    email = db.Column(db.String(120), nullable=False)
    submission_date = db.Column(db.Date)
    last_name_kanji = db.Column(db.String(50), nullable=False)
    first_name_kanji = db.Column(db.String(50), nullable=False)
    last_name_kana = db.Column(db.String(50), nullable=False)
    first_name_kana = db.Column(db.String(50), nullable=False)
    post_code = db.Column(db.String(10), nullable=False)
    address = db.Column(db.String(255), nullable=False)
    tel_main = db.Column(db.String(20), nullable=False)
    tel_sub = db.Column(db.String(20))
    exp_jp = db.Column(db.Text)
    exp_other = db.Column(db.Text)
    hobbies = db.Column(db.String(255))
    skills = db.Column(db.String(255))
    qualifications = db.Column(db.String(255))
    intent = db.Column(db.Text)


class Student(db.Model):
    """
    生徒情報テーブル（アカウントとは独立した単体のカルテ）
    """

    __tablename__ = "students"

    id = db.Column(db.Integer, primary_key=True)
    face_photo_path = db.Column(db.String(255), nullable=False)  # (1)
    name_kana = db.Column(db.String(100), nullable=False)  # (2)
    country_of_origin = db.Column(db.String(50), nullable=False)  # (3)
    native_language = db.Column(db.String(50), nullable=False)  # (4)
    other_languages = db.Column(db.String(100))  # (5)
    occupation = db.Column(db.String(50))  # (6)
    residential_area = db.Column(db.String(50), nullable=False)  # (7)
    jlpt_level = db.Column(db.String(10), nullable=False)  # (8)
    learning_purpose = db.Column(db.Text)  # (9)
    life_troubles = db.Column(db.Text)  # (10)
    how_knew_class = db.Column(db.String(50), nullable=False)  # (11)
    how_knew_class_other = db.Column(db.Text)  # (12)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # 生徒に紐づく学習記録（1対多）
    # ※LearningRecord側の 'student' バックレフと自動接続されます。cascadeにより生徒削除時に記録も消えます。
    learning_records = db.relationship(
        "LearningRecord", backref="student", cascade="all, delete-orphan"
    )


class LearningRecord(db.Model):
    __tablename__ = "learning_records"
    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(
        db.Integer, db.ForeignKey("students.id", ondelete="CASCADE"), nullable=False
    )
    staff_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)

    # 画像の項目に対応
    lesson_date = db.Column(db.Date, default=datetime.utcnow)  # レッスン日
    textbook_progress = db.Column(db.String(50))  # 第〇回目（選択式）
    today_learning_content = db.Column(db.Text)  # 学習内容（一般）
    recorded_at = db.Column(db.DateTime, default=datetime.utcnow)


class Meeting(db.Model):
    __tablename__ = "meetings"
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)  # ミーティングタイトル
    date = db.Column(db.Date, nullable=False)
    pdf_path = db.Column(db.String(255), nullable=True)
    content = db.Column(db.Text, nullable=False)  # 議事録内容
    created_by = db.Column(db.Integer, db.ForeignKey("users.id"))  # 作成者
    attachments = db.relationship(
        "Attachment", backref="meeting", lazy=True, cascade="all, delete-orphan"
    )


class Attachment(db.Model):
    __tablename__ = "attachments"
    id = db.Column(db.Integer, primary_key=True)
    filename = db.Column(db.String(255), nullable=False)  # 保存時のファイル名
    original_name = db.Column(db.String(255), nullable=False)  # 元のファイル名
    meeting_id = db.Column(db.Integer, db.ForeignKey("meetings.id"), nullable=False)
