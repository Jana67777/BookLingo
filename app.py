from flask import Flask, render_template, request, redirect, url_for, flash, jsonify
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime
import requests
import os
import re

app = Flask(__name__)
app.config['SECRET_KEY'] = 'andersen_secret_key_12345'
# 允许上传文件大小限制为 16MB
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024

# Vercel 部署环境适配：Vercel 的根目录是只读的，SQLite 需要写在 /tmp 目录下，或者使用 PostgreSQL
if os.environ.get('SQLALCHEMY_DATABASE_URI') or os.environ.get('DATABASE_URL'):
    # 如果用户在 Vercel 或环境变量中配置了外部数据库（如 Supabase Postgres），优先使用
    # SQLAlchemy 要求 postgresql:// 前缀，而有些提供商给的是 postgres://
    db_uri = os.environ.get('SQLALCHEMY_DATABASE_URI') or os.environ.get('DATABASE_URL')
    if db_uri.startswith("postgres://"):
        db_uri = db_uri.replace("postgres://", "postgresql://", 1)
    app.config['SQLALCHEMY_DATABASE_URI'] = db_uri
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
    vocabs = db.relationship('Vocab', backref='user', lazy=True, cascade="all, delete-orphan")
    books = db.relationship('Book', backref='owner', lazy=True, cascade="all, delete-orphan")
    highlights = db.relationship('Highlight', backref='user', lazy=True, cascade="all, delete-orphan")
    notes = db.relationship('Note', backref='user', lazy=True, cascade="all, delete-orphan")

class Book(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(255), nullable=False)
    content = db.Column(db.Text, nullable=False)
    total_pages = db.Column(db.Integer, default=1)
    current_page = db.Column(db.Integer, default=1) # 记录用户阅读进度
    upload_date = db.Column(db.DateTime, default=datetime.utcnow)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    
class Highlight(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    text = db.Column(db.Text, nullable=False) # 高亮的文本内容
    page_num = db.Column(db.Integer, nullable=False) # 所在页码
    start_offset = db.Column(db.Integer, nullable=False) # 在该页内的起始位置(可选)
    end_offset = db.Column(db.Integer, nullable=False) # 在该页内的结束位置(可选)
    color = db.Column(db.String(20), default="#fef08a") # 高亮颜色
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    book_id = db.Column(db.Integer, db.ForeignKey('book.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)

class Note(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    content = db.Column(db.Text, nullable=False) # 笔记内容
    highlight_id = db.Column(db.Integer, db.ForeignKey('highlight.id'), nullable=True) # 关联的高亮（如果有）
    page_num = db.Column(db.Integer, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    book_id = db.Column(db.Integer, db.ForeignKey('book.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)

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

# --- 阅读器核心逻辑 ---
PAGE_SIZE = 2000

def paginate_text(text: str, page_size: int):
    if not text:
        return []
    pages = []
    i = 0
    n = len(text)
    while i < n:
        end = min(i + page_size, n)
        if end < n:
            window_start = max(i, end - 200)
            chunk = text[window_start:end]
            m = None
            for match in re.finditer(r"\s", chunk):
                m = match
            if m:
                safe_end = window_start + m.start()
                if safe_end <= i:
                    safe_end = end
            else:
                forward_end = min(n, end + 200)
                fchunk = text[end:forward_end]
                fm = re.search(r"\s", fchunk)
                if fm:
                    safe_end = end + fm.start()
                else:
                    safe_end = end
        else:
            safe_end = end
        pages.append(text[i:safe_end])
        i = safe_end
    return pages

def get_default_book_content():
    default_book_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "Andersen's_fairy_tales.txt")
    if os.path.exists(default_book_path):
        try:
            with open(default_book_path, "r", encoding="utf-8") as f:
                return f.read()
        except Exception as e:
            print("Failed to load default book:", e)
    return "Welcome to BookLingo! Please login and upload a book to start reading."

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
    source = data.get('source', 'BookLingo')
    
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

# --- 阅读器相关路由 (移植自旧版本并重构为持久化) ---
@app.route('/api/page')
def api_page():
    book_id = request.args.get('book_id')
    
    # 未登录或未指定书籍时，提供默认的展示内容
    if not current_user.is_authenticated or not book_id:
        text = get_default_book_content()
        pages = paginate_text(text, PAGE_SIZE)
        total = max(1, len(pages))
        try:
            page = int(request.args.get("page", "1"))
        except Exception:
            page = 1
        page = max(1, min(page, total))
        return jsonify({
            "page": page, 
            "total_pages": total, 
            "page_size": PAGE_SIZE, 
            "content": pages[page-1] if pages else "", 
            "book_title": "BookLingo 演示读物",
            "book_id": None
        })
        
    # 已登录并读取专属书籍
    book = db.session.get(Book, int(book_id))
    if not book or book.user_id != current_user.id:
        return jsonify({"error": "Book not found"}), 404
        
    pages = paginate_text(book.content, PAGE_SIZE)
    total = max(1, len(pages))
    
    try:
        page = int(request.args.get("page", "1"))
    except Exception:
        page = book.current_page
        
    page = max(1, min(page, total))
    
    # 自动保存阅读进度
    if book.current_page != page:
        book.current_page = page
        db.session.commit()
        
    # 获取该页的高亮和笔记
    highlights = Highlight.query.filter_by(book_id=book.id, page_num=page).all()
    notes = Note.query.filter_by(book_id=book.id, page_num=page).all()

    return jsonify({
        "page": page, 
        "total_pages": total, 
        "page_size": PAGE_SIZE, 
        "content": pages[page-1] if pages else "", 
        "book_title": book.title,
        "book_id": book.id,
        "highlights": [{"id": h.id, "text": h.text, "color": h.color} for h in highlights],
        "notes": [{"id": n.id, "content": n.content, "highlight_id": n.highlight_id} for n in notes]
    })

@app.route('/api/upload', methods=['POST'])
@login_required
def upload_file():
    if 'file' not in request.files:
        return jsonify({"error": "No file part"}), 400
    file = request.files['file']
    if file.filename == '':
        return jsonify({"error": "No selected file"}), 400
    
    try:
        content = file.read()
        text = None
        for enc in ['utf-8', 'gbk', 'gb18030', 'latin-1']:
            try:
                text = content.decode(enc)
                break
            except UnicodeDecodeError:
                continue
        
        if text is None:
            return jsonify({"error": "Unsupported encoding"}), 400
            
        title = os.path.splitext(file.filename)[0]
        pages = paginate_text(text, PAGE_SIZE)
        
        # 将书本存入数据库
        new_book = Book(
            title=title,
            content=text,
            total_pages=len(pages),
            current_page=1,
            user_id=current_user.id
        )
        db.session.add(new_book)
        db.session.commit()
        
        return jsonify({"success": True, "title": title, "book_id": new_book.id, "total_pages": len(pages)})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/books', methods=['GET'])
@login_required
def list_books():
    books = Book.query.filter_by(user_id=current_user.id).order_by(Book.upload_date.desc()).all()
    return jsonify({
        "books": [{"id": b.id, "title": b.title, "current_page": b.current_page, "total_pages": b.total_pages} for b in books]
    })

# --- 高亮与笔记 API ---
@app.route('/api/highlight', methods=['POST'])
@login_required
def add_highlight():
    data = request.get_json()
    new_highlight = Highlight(
        text=data['text'],
        page_num=data['page_num'],
        start_offset=data.get('start_offset', 0),
        end_offset=data.get('end_offset', 0),
        color=data.get('color', '#fef08a'),
        book_id=data['book_id'],
        user_id=current_user.id
    )
    db.session.add(new_highlight)
    db.session.commit()
    
    # 如果同时提交了笔记
    note_id = None
    if data.get('note_content'):
        new_note = Note(
            content=data['note_content'],
            highlight_id=new_highlight.id,
            page_num=data['page_num'],
            book_id=data['book_id'],
            user_id=current_user.id
        )
        db.session.add(new_note)
        db.session.commit()
        note_id = new_note.id
        
    return jsonify({"success": True, "highlight_id": new_highlight.id, "note_id": note_id})

@app.route('/')
def index():
    return render_template('index.html')

if __name__ == '__main__':
    # host='0.0.0.0' allows it to be accessed on the local network
    app.run(debug=True, host='0.0.0.0', port=5000)
