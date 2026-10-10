"""Local development settings. Deployment requires a separate production configuration."""
import os
import secrets
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
SITE_DIR = BASE_DIR.parent / 'academic-preview'
DATA_DIR = Path(os.environ.get('TEACHING_DATA_DIR', str(Path(os.environ.get('LOCALAPPDATA', str(Path.home()))) / 'EurasiaTeachingPlatform' / 'data')))
DATA_DIR.mkdir(parents=True, exist_ok=True)
key_file = DATA_DIR / 'secret-key'
if not key_file.exists():
    key_file.write_text(secrets.token_urlsafe(64), encoding='utf8')
SECRET_KEY = key_file.read_text(encoding='utf8').strip()
DEBUG = False
ALLOWED_HOSTS = ['127.0.0.1', 'localhost', '[::1]']
INSTALLED_APPS = ['django.contrib.auth', 'django.contrib.contenttypes', 'django.contrib.sessions', 'django.contrib.messages', 'django.contrib.staticfiles', 'learning']
MIDDLEWARE = ['django.middleware.security.SecurityMiddleware', 'learning.middleware.PrivatePageCacheMiddleware', 'django.contrib.sessions.middleware.SessionMiddleware', 'django.middleware.common.CommonMiddleware', 'django.middleware.csrf.CsrfViewMiddleware', 'django.contrib.auth.middleware.AuthenticationMiddleware', 'django.contrib.messages.middleware.MessageMiddleware', 'django.middleware.clickjacking.XFrameOptionsMiddleware']
ROOT_URLCONF = 'platform_config.urls'
TEMPLATES = [{'BACKEND': 'django.template.backends.django.DjangoTemplates', 'DIRS': [BASE_DIR / 'templates'], 'APP_DIRS': True, 'OPTIONS': {'context_processors': ['django.template.context_processors.request', 'django.contrib.auth.context_processors.auth', 'django.contrib.messages.context_processors.messages', 'learning.context_processors.dashboard_navigation']}}]
DATABASES = {'default': {'ENGINE': 'django.db.backends.sqlite3', 'NAME': DATA_DIR / 'learning.sqlite3', 'OPTIONS': {'timeout': 20}}}
AUTH_PASSWORD_VALIDATORS = [{'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'}, {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator', 'OPTIONS': {'min_length': 12}}, {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'}, {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'}]
TIME_ZONE = 'Asia/Shanghai'
USE_TZ = True
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'
STATIC_URL = '/platform-assets/'
LOGIN_URL = '/login/'
LOGIN_REDIRECT_URL = '/'
LOGOUT_REDIRECT_URL = '/login/'
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = 'Lax'
CSRF_COOKIE_SAMESITE = 'Lax'
X_FRAME_OPTIONS = 'DENY'
DATA_UPLOAD_MAX_MEMORY_SIZE = 1024 * 1024
