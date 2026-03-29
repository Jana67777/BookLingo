from flask import Flask, render_template, request, redirect, url_for, flash, jsonify
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash
import requests
import os

app = Flask(__name__)
app.config['SECRET_KEY'] = 'andersen_secret_key_12345'

# Vercel 部署环境适配：Vercel 的根目录是只读的，SQLite 需要写在 /tmp 目录下，或者使用 PostgreSQL
if os.environ.get('SQLALCHEMY_DATABASE_URI'):
    # 如果用户在 Vercel 配置了外部数据库（如 Postgres），优先使用
    app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('SQLALCHEMY_DATABASE_URI').replace("postgres://", "postgresql://", 1)
elif os.environ.get('VERCEL_ENV') or os.environ.get('VERCEL') or '/var/task' in os.path.abspath(__file__):
    # 注意：Vercel 是 Serverless 环境，/tmp 目录下的数据在实例销毁时会丢失。
    # 推荐后续替换为 Vercel Postgres 等云数据库
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:////tmp/andersen.db'
else:
    basedir = os.path.abspath(os.path.dirname(__file__))
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + os.path.join(basedir, 'andersen.db')
    
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

# --- 数据库模型 (Task 3) ---

class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(150), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)
    vocabs = db.relationship('Vocab', backref='user', lazy=True)

class Vocab(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    word = db.Column(db.String(100), nullable=False)
    translation = db.Column(db.String(200), nullable=False)
    context = db.Column(db.Text, nullable=True) # 出处句子
    source = db.Column(db.String(100), nullable=True) # 来源故事
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)

@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))

# 初始化数据库表
with app.app_context():
    db.create_all()

# --- 路由 (Task 1: Auth) ---
@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        
        user = User.query.filter_by(username=username).first()
        if user:
            flash('用户名已存在', 'error')
            return redirect(url_for('register'))
            
        new_user = User(username=username, password_hash=generate_password_hash(password, method='pbkdf2:sha256'))
        db.session.add(new_user)
        db.session.commit()
        
        flash('注册成功，请登录', 'success')
        return redirect(url_for('login'))
        
    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        
        user = User.query.filter_by(username=username).first()
        if user and check_password_hash(user.password_hash, password):
            login_user(user)
            flash('登录成功', 'success')
            return redirect(url_for('index'))
        else:
            flash('用户名或密码错误', 'error')
            
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('index'))

# --- 核心业务路由 (Task 2 & Task 3) ---

@app.route('/api/translate', methods=['POST'])
@login_required
def translate_word():
    data = request.get_json()
    word = data.get('word', '').strip()
    
    if not word:
        return jsonify({'error': 'No word provided'}), 400
        
    # 调用免费翻译API (MyMemory)
    url = "https://api.mymemory.translated.net/get"
    try:
        response = requests.get(url, params={'q': word, 'langpair': 'en|zh-CN'})
        if response.status_code == 200:
            result = response.json()
            translation = result['responseData']['translatedText']
            return jsonify({'word': word, 'translation': translation})
        return jsonify({'error': 'Translation API failed'}), 500
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/vocab/add', methods=['POST'])
@login_required
def add_vocab():
    data = request.get_json()
    word = data.get('word')
    translation = data.get('translation')
    context = data.get('context')
    source = data.get('source', '安徒生童话')
    
    if not word or not translation:
        return jsonify({'error': 'Missing word or translation'}), 400
        
    # 检查是否已在生词本中
    existing = Vocab.query.filter_by(user_id=current_user.id, word=word).first()
    if existing:
        return jsonify({'message': '已在生词本中'})
        
    new_vocab = Vocab(
        word=word,
        translation=translation,
        context=context,
        source=source,
        user_id=current_user.id
    )
    db.session.add(new_vocab)
    db.session.commit()
    return jsonify({'message': '成功加入生词本', 'id': new_vocab.id})

@app.route('/vocab')
@login_required
def vocab_book():
    vocabs = Vocab.query.filter_by(user_id=current_user.id).order_by(Vocab.id.desc()).all()
    return render_template('vocab.html', vocabs=vocabs)

@app.route('/')
def index():
    return render_template('index.html')

if __name__ == '__main__':
    # host='0.0.0.0' allows it to be accessed on the local network
    app.run(debug=True, host='0.0.0.0', port=5000)
