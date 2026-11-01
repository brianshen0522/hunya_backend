from waitress import serve
from flask import Flask, request, jsonify, send_file
from flask_sqlalchemy import SQLAlchemy
from flask_cors import CORS
from flask_jwt_extended import JWTManager, create_access_token, jwt_required, get_jwt_identity
from werkzeug.security import generate_password_hash, check_password_hash
from subprocess import check_output
from datetime import datetime, timedelta, timezone
from magika import Magika
from PIL import Image
import ast
import enum
import hashlib
import hmac
import jwt
import os
import io
import re
import json
import secrets
import tempfile
import time
import shutil
import requests
from dotenv import load_dotenv
from verify import docx_to_json, image_to_json, compare_jsons

# Load environment variables
load_dotenv()

# Initialize Flask app
app = Flask(__name__)
CORS(app, origins=[origin.strip() for origin in os.getenv("CORS_ORIGINS", "*").split(",")])

# Configuration
app.config['SQLALCHEMY_DATABASE_URI'] = f'postgresql://{os.getenv("DB_USER")}:{os.getenv("DB_PASSWORD")}@{os.getenv("DB_HOST")}:{os.getenv("DB_PORT")}/{os.getenv("DB_NAME")}'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['JWT_SECRET_KEY'] = os.getenv("SECRET_KEY")
app.config['JWT_ACCESS_TOKEN_EXPIRES'] = timedelta(minutes=int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", 3000)))
app.config['MAX_CONTENT_LENGTH'] = int(os.getenv("MAX_UPLOAD_MB", 50)) * 1024 * 1024

upload_path = os.getenv("FILES_UPLOAD_PATH")
doc_to_pdf_url = os.getenv("DOC_TO_PDF_URL", "http://162.38.3.101:8101/doc_to_pdf")
doc_to_pdf_token = os.getenv("DOC_TO_PDF_TOKEN")
DOC_TO_PDF_TIMEOUT = 180
DOCX_MIME_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"

# Initialize extensions
db = SQLAlchemy(app)
jwt = JWTManager(app)

# Enums and Models
class UserRole(str, enum.Enum):
    ADMIN = "admin"
    USER = "user"

class User(db.Model):
    __tablename__ = "users"
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String, unique=True, index=True)
    email = db.Column(db.String, unique=True, index=True)
    password = db.Column(db.String)
    role = db.Column(db.Enum(UserRole))
    used_credit = db.Column(db.Float, default=0)

class Verification(db.Model):
    __tablename__ = "verifications"
    id = db.Column(db.Integer, primary_key=True)
    verification_name = db.Column(db.String)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    docx_path = db.Column(db.String)
    docx_filename = db.Column(db.String)
    pdf = db.Column(db.Boolean, default=False)
    docx_hash = db.Column(db.String(64))
    image_path = db.Column(db.String)
    image_filename = db.Column(db.String)
    image_hash = db.Column(db.String(64))
    image_ocr_scope = db.Column(db.String)
    docx_json = db.Column(db.String)
    ocr_json = db.Column(db.String)
    differences_json = db.Column(db.String)
    status = db.Column(db.String, default="pending")
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

@app.after_request
def set_security_headers(response):
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-Frame-Options'] = 'DENY'
    return response

# Utility Functions
def get_current_user():
    username = get_jwt_identity()
    return User.query.filter_by(username=username).first()

def calculate_file_hash(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()

def process_image(image_content: bytes, image_path: str):
    image = Image.open(io.BytesIO(image_content))
    os.makedirs(os.path.dirname(image_path), exist_ok=True)
    image.save(image_path)

def crop_image(image_path: str, crop_info: str) -> str:
    try:
        crop_height, crop_width, crop_x, crop_y = json.loads(crop_info)
        img = Image.open(image_path)
        img_width, img_height = img.size

        x = max(0, min(round((crop_x / 100) * img_width), img_width - 1))
        y = max(0, min(round((crop_y / 100) * img_height), img_height - 1))
        width = max(1, min(round((crop_width / 100) * img_width), img_width - x))
        height = max(1, min(round((crop_height / 100) * img_height), img_height - y))

        crop_box = (x, y, x + width, y + height)
        cropped_img = img.crop(crop_box)

        base_name, ext = os.path.splitext(image_path)
        cropped_image_path = f"{base_name}_cropped{ext}"
        cropped_img.save(cropped_image_path, "PNG")
        return cropped_image_path

    except Exception as e:
        raise RuntimeError(f"Failed to crop image: {str(e)}")

# Routes
@app.route('/token', methods=['POST'])
def login():
    username = request.form.get('username')
    password = request.form.get('password')
    
    user = User.query.filter_by(username=username).first()
    if not user or not password or not check_password_hash(user.password, password):
        return jsonify({"error": "Invalid credentials"}), 400

    access_token = create_access_token(identity=username)
    return jsonify(access_token=access_token, token_type="bearer")

@app.route('/users', methods=['POST'])
@jwt_required()
def create_user():
    current_user = get_current_user()
    if current_user.role != UserRole.ADMIN:
        return jsonify({"error": "Unauthorized"}), 403

    data = request.get_json()
    if User.query.filter((User.username == data['username']) | 
                        (User.email == data['email'])).first():
        return jsonify({"error": "Username or email already exists"}), 400

    new_user = User(
        username=data['username'],
        email=data['email'],
        password=generate_password_hash(data['password']),
        role=data['role']
    )
    db.session.add(new_user)
    db.session.commit()
    return jsonify({"message": "User created"})

@app.route('/users/me', methods=['GET'])
@jwt_required()
def read_user():
    current_user = get_current_user()
    return jsonify({
        'username': current_user.username,
        'email': current_user.email,
        'role': current_user.role,
        'used_credit': current_user.used_credit
    })

@app.route('/verifications', methods=['GET'])
@jwt_required()
def list_verifications():
    current_user = get_current_user()
    verifications = Verification.query.filter_by(user_id=current_user.id).all()
    return jsonify([{
        'id': v.id,
        'verification_name': v.verification_name,
        'status': v.status,
        'created_at': v.created_at.isoformat()
    } for v in verifications])

@app.route('/verifications', methods=['POST'])
@jwt_required()
def create_verification():
    current_user = get_current_user()
    if current_user.role != UserRole.USER:
        return jsonify({"error": "Unauthorized"}), 403

    # Get verification_name from the query parameters
    verification_name = request.args.get('verification_name')
    if not verification_name:
        return jsonify({"error": "verification_name is required"}), 400

    verification = Verification(verification_name=verification_name, user_id=current_user.id)
    db.session.add(verification)
    db.session.commit()
    return jsonify({
        "id": verification.id,
        "verification_name": verification_name
    })

@app.route('/verifications/<int:verification_id>', methods=['GET'])
@jwt_required()
def get_verification_info(verification_id):
    current_user = get_current_user()
    verification = Verification.query.get_or_404(verification_id)

    if current_user.role != UserRole.ADMIN and verification.user_id != current_user.id:
        return jsonify({"error": "Not authorized"}), 403

    docx_exists = os.path.exists(verification.docx_path) if verification.docx_path else False
    image_exists = os.path.exists(verification.image_path) if verification.image_path else False
    pdf_exists = os.path.exists(f"{upload_path}/pdf/{verification_id}.pdf") if verification.pdf else False

    differences = None
    if verification.differences_json:
        try:
            differences = ast.literal_eval(verification.differences_json)
        except Exception as e:
            differences = {"error": f"Failed to parse differences: {str(e)}"}

    return jsonify({
        "verification_id": verification.id,
        "verification_name": verification.verification_name,
        "status": verification.status,
        "created_at": verification.created_at.isoformat(),
        "docx_info": {
            "exists": docx_exists,
            "filename": verification.docx_filename,
            "hash": verification.docx_hash
        },
        "pdf_info": {
            "exists": pdf_exists,
            "available": verification.pdf
        },
        "image_info": {
            "exists": image_exists,
            "filename": verification.image_filename,
            "hash": verification.image_hash,
            "ocr_scope": verification.image_ocr_scope
        },
        "differences": differences
    })

@app.route('/verifications/<int:verification_id>/upload', methods=['POST'])
@jwt_required()
def upload_files(verification_id):
    time.sleep(10)
    current_user = get_current_user()
    if current_user.role != UserRole.USER:
        return jsonify({"error": "Unauthorized"}), 403

    verification = Verification.query.filter_by(
        id=verification_id,
        user_id=current_user.id
    ).first_or_404()

    docx_file = request.files.get('docx_file')
    image_file = request.files.get('image_file')
    ocr_scope = request.form.get('ocr_scope', 'full')

    if not ((docx_file or verification.docx_path) and (image_file or verification.image_path)):
        return jsonify({"error": "Missing required files"}), 400

    magika = Magika()
    try:
        # Process DOCX
        if docx_file:
            docx_content = docx_file.read()
            docx_hash = calculate_file_hash(docx_content)
            
            if verification.docx_hash != docx_hash:
                if magika.identify_bytes(docx_content).output.mime_type != DOCX_MIME_TYPE:
                    return jsonify({"error": "Invalid DOCX type"}), 400

                docx_tmp_path = f"{upload_path}/docx/{verification_id}_tmp.docx"
                docx_path = f"{upload_path}/docx/{verification_id}.docx"
                
                os.makedirs(os.path.dirname(docx_tmp_path), exist_ok=True)
                with open(docx_tmp_path, "wb") as buffer:
                    buffer.write(docx_content)

                # Convert DOCX to PDF
                with open(docx_tmp_path, 'rb') as docx_tmp_file:
                    response = requests.post(
                        doc_to_pdf_url,
                        files={'file': docx_tmp_file},
                        headers={'X-Doc-To-Pdf-Token': doc_to_pdf_token} if doc_to_pdf_token else None,
                        timeout=DOC_TO_PDF_TIMEOUT
                    )

                if response.status_code == 200:
                    pdf_tmp_path = f"{upload_path}/pdf/{verification_id}_tmp.pdf"
                    pdf_path = f"{upload_path}/pdf/{verification_id}.pdf"
                    os.makedirs(os.path.dirname(pdf_tmp_path), exist_ok=True)
                    
                    with open(pdf_tmp_path, 'wb') as pdf_file:
                        pdf_file.write(response.content)
                    verification.pdf = True
                else:
                    verification.pdf = False

                docx_json = docx_to_json(pdf_tmp_path)
                if isinstance(docx_json, dict) and "error" in docx_json:
                    os.remove(docx_tmp_path)
                    return jsonify({
                        "system_component": "docx_processing",
                        "error_type": docx_json["error"],
                        "missing_elements": docx_json.get("missing", []),
                        "guidance": "Required fields are missing in the DOCX document"
                    }), 200

                shutil.move(docx_tmp_path, docx_path)
                shutil.move(pdf_tmp_path, pdf_path)

                verification.docx_path = docx_path
                verification.docx_filename = docx_file.filename
                verification.docx_json = json.dumps(docx_json, ensure_ascii=False)
                verification.docx_hash = docx_hash

        # Process Image
        if image_file:
            image_content = image_file.read()
            image_hash = calculate_file_hash(image_content)
            
            if verification.image_hash != image_hash or verification.image_ocr_scope != ocr_scope:
                if not magika.identify_bytes(image_content).output.mime_type.startswith('image/'):
                    return jsonify({"error": "Invalid image type"}), 400

                image_path = f"{upload_path}/images/{verification_id}.png"
                process_image(image_content, image_path)

                if ocr_scope == 'full':
                    ocr_json = image_to_json(image_path, 'full')
                else:
                    crop = crop_image(image_path, ocr_scope)
                    ocr_json = image_to_json(crop, 'full')

                if ocr_json is None:
                    return jsonify({
                        "system_component": "image_processing",
                        "error_type": "NUTRITION_TABLE_MISSING",
                        "guidance": "The nutrition table could not be detected in the image."
                    }), 200

                verification.image_path = image_path
                verification.image_filename = image_file.filename
                verification.image_hash = image_hash
                verification.image_ocr_scope = ocr_scope
                verification.ocr_json = json.dumps(ocr_json, ensure_ascii=False)

        # Compare if both files are ready
        if verification.docx_json and verification.ocr_json:
            differences = compare_jsons(
                json.loads(verification.docx_json),
                json.loads(verification.ocr_json)
            )
            verification.differences_json = str(differences)
            verification.status = "completed"
            db.session.commit()
            return jsonify({
                "message": "Verification completed",
                "differences": differences
            })

        db.session.commit()
        return jsonify({
            "message": "Files processed",
            "status": "pending"
        })

    except Exception as e:
        if 'docx_path' in locals() and os.path.exists(docx_path):
            os.remove(docx_path)
        if 'image_path' in locals() and os.path.exists(image_path):
            os.remove(image_path)
        app.logger.exception("Failed to process files for verification %s", verification_id)
        return jsonify({"error": "Failed to process files"}), 500

@app.route('/verifications/<int:verification_id>/docx', methods=['GET'])
@jwt_required()
def download_docx(verification_id):
    current_user = get_current_user()
    verification = Verification.query.filter_by(
        id=verification_id,
        user_id=current_user.id
    ).first_or_404()

    if not verification.docx_path:
        return jsonify({"error": "DOCX file not found"}), 404

    if not os.path.exists(verification.docx_path):
        return jsonify({"error": "File no longer exists on server"}), 404

    return send_file(
        verification.docx_path,
        mimetype="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        as_attachment=True,
        download_name=verification.docx_filename
    )

@app.route('/verifications/<int:verification_id>/pdf', methods=['GET'])
@jwt_required()
def download_pdf(verification_id):
    current_user = get_current_user()
    verification = Verification.query.filter_by(
        id=verification_id,
        user_id=current_user.id
    ).first_or_404()

    if not verification.pdf:
        return jsonify({"error": "PDF file not found"}), 404

    pdf_path = f"{upload_path}/pdf/{verification_id}.pdf"
    if not os.path.exists(pdf_path):
        return jsonify({"error": "File no longer exists on server"}), 404

    return send_file(
        pdf_path,
        mimetype="application/pdf",
        as_attachment=True,
        download_name=f"{verification.verification_name}.pdf"
    )

@app.route('/verifications/<int:verification_id>/image', methods=['GET'])
@jwt_required()
def download_image(verification_id):
    current_user = get_current_user()
    verification = Verification.query.filter_by(
        id=verification_id,
        user_id=current_user.id
    ).first_or_404()

    if not verification.image_path:
        return jsonify({"error": "Image file not found"}), 404

    if not os.path.exists(verification.image_path):
        return jsonify({"error": "File no longer exists on server"}), 404

    return send_file(
        verification.image_path,
        mimetype="image/jpeg",
        as_attachment=True,
        download_name=verification.image_filename
    )

@app.route('/verifications/<int:verification_id>/rename', methods=['PUT'])
@jwt_required()
def rename_verification(verification_id):
    current_user = get_current_user()
    if current_user.role != UserRole.USER:
        return jsonify({"error": "Only users can rename verifications"}), 403

    verification = Verification.query.filter_by(
        id=verification_id,
        user_id=current_user.id
    ).first_or_404()

    data = request.get_json()
    verification.verification_name = data['verification_name']
    db.session.commit()

    return jsonify({
        "message": "Verification renamed successfully",
        "verification_id": verification_id,
        "new_name": verification.verification_name
    })

@app.route('/verifications/<int:verification_id>', methods=['DELETE'])
@jwt_required()
def delete_verification(verification_id):
    current_user = get_current_user()
    if current_user.role != UserRole.USER:
        return jsonify({"error": "Unauthorized"}), 403

    verification = Verification.query.filter_by(
        id=verification_id,
        user_id=current_user.id
    ).first_or_404()

    # Delete associated files
    for path in [verification.docx_path, verification.image_path]:
        if path and os.path.exists(path):
            os.remove(path)
    
    # Delete PDF if it exists
    pdf_path = f"{upload_path}/pdf/{verification_id}.pdf"
    if os.path.exists(pdf_path):
        os.remove(pdf_path)

    db.session.delete(verification)
    db.session.commit()
    return jsonify({"message": "Verification deleted"})

@app.route('/doc_to_pdf', methods = ['GET','POST'])
def upload_file():
    if request.method == 'GET':
        return '''
        <!doctype html>
        <title>Upload new File</title>
        <h1>Upload new File</h1>
        <form method=post enctype=multipart/form-data>
        <input type=file name=file>
        <input type=submit value=Upload>
        </form>
        '''

    if doc_to_pdf_token and not hmac.compare_digest(
        request.headers.get('X-Doc-To-Pdf-Token', '').encode(),
        doc_to_pdf_token.encode()
    ):
        return jsonify({'message' : 'Unauthorized'}), 401

    if 'file' not in request.files:
        resp = jsonify({'message' : 'No file part in the request'})
        resp.status_code = 400
        return resp
    file = request.files['file']
    if file.filename == '':
        resp = resp = jsonify({'message' : 'No file selected for uploading'})
        resp.status_code = 400
        return resp
    content = file.read()
    if Magika().identify_bytes(content).output.mime_type not in (DOCX_MIME_TYPE, "application/msword"):
        return jsonify({'message' : 'Invalid document type'}), 400

    try:
        with tempfile.TemporaryDirectory() as workdir:
            docx_path = os.path.join(workdir, 'document.docx')
            with open(docx_path, 'wb') as buffer:
                buffer.write(content)
            check_output([
                'libreoffice', f'-env:UserInstallation=file://{workdir}/profile',
                '--headless', '--convert-to', 'pdf', '--outdir', workdir, docx_path
            ], timeout=DOC_TO_PDF_TIMEOUT)
            with open(os.path.join(workdir, 'document.pdf'), 'rb') as pdf_file:
                pdf_content = pdf_file.read()
        return send_file(io.BytesIO(pdf_content), mimetype='application/pdf', download_name='document.pdf')
    except Exception:
        app.logger.exception("Failed to convert document")
        return jsonify({'message' : 'Failed to convert document'}), 500

def initial_password(env_name, username):
    password = os.getenv(env_name)
    if not password:
        password = secrets.token_urlsafe(16)
        print(f'Generated initial password for {username}: {password}')
    return password

def create_default_users():
    if not User.query.first():
        users = [
            User(
                username="admin",
                email="admin@example.com",
                password=generate_password_hash(initial_password("DEFAULT_ADMIN_PASSWORD", "admin")),
                role=UserRole.ADMIN
            ),
            User(
                username="user",
                email="user@example.com",
                password=generate_password_hash(initial_password("DEFAULT_USER_PASSWORD", "user")),
                role=UserRole.USER
            )
        ]
        for user in users:
            db.session.add(user)
        db.session.commit()

# Initialize database and create default users
def init_app():
    with app.app_context():
        db.create_all()
        create_default_users()

if __name__ == "__main__":
    init_app()
    if app.config['JWT_SECRET_KEY'] == 'your-secret-key':
        print('WARNING: SECRET_KEY is the published placeholder; tokens can be forged until it is changed')
    if not doc_to_pdf_token:
        print('WARNING: DOC_TO_PDF_TOKEN is not set; /doc_to_pdf accepts unauthenticated uploads')
    print('SERVER STARTING')
    serve(app, host=os.getenv("SERVER_HOST"), port=os.getenv("SERVER_PORT"))
