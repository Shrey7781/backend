import bcrypt

def hash_password(password: str) -> str:
    # Directly use bcrypt library to avoid passlib's init-time checks
    pwd_bytes = password.encode('utf-8')
    # bcrypt handles salting and hashing in one go
    salt = bcrypt.gensalt()
    hashed = bcrypt.hashpw(pwd_bytes[:72], salt)
    return hashed.decode('utf-8')

def verify_password(plain_password: str, hashed_password: str) -> bool:
    password_bytes = plain_password.encode('utf-8')
    hashed_bytes = hashed_password.encode('utf-8')
    return bcrypt.checkpw(password_bytes[:72], hashed_bytes)