import os
from cryptography.fernet import Fernet, InvalidToken

# サーバー起動時に使用するマスターキー (一度生成したら固定する必要があります)
# 本番環境では環境変数などに保存してください
MASTER_KEY = os.environ.get("ENCRYPTION_KEY") or Fernet.generate_key()
cipher = Fernet(MASTER_KEY)


def encrypt_value(value: str) -> str:
    """文字列を暗号化して返す"""
    return cipher.encrypt(value.encode()).decode()


def decrypt_value(encrypted_value: str) -> str:
    try:
        return cipher.decrypt(encrypted_value.encode()).decode()
    except InvalidToken:
        print("エラー: 復号に失敗しました。キーが異なるか、データが破損しています。")
        return None  # または例外を再送出
    except Exception as e:
        print(f"予期せぬエラー: {e}")
        return None
