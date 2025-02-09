# HunyProof Backend

HunyProof is a backend system designed for document verification and OCR-based proofreading. It utilizes an LLM (Large Language Model) to compare extracted OCR text with document text for validation.

## Features
- **OCR Processing**: Uses Azure OCR for text recognition.
- **Document Verification**: Compares DOCX and image-based OCR data.
- **JWT Authentication**: Secures API endpoints with token-based authentication.
- **PostgreSQL Integration**: Stores verification data.
- **Flask-based API**: Provides endpoints for user authentication and document processing.

## Installation

### Prerequisites
Ensure you have the following installed:
- Docker & Docker Compose
- Python 3.8+
- PostgreSQL 15+

### Environment Setup
Create a `.env` file in the project root and configure the following variables:
```env
# Server
SERVER_HOST=0.0.0.0
SERVER_PORT=8100
FILES_UPLOAD_PATH=./uploads

# Database
DB_HOST=hunyproof-postgres
DB_PORT=5432
DB_NAME=hunyproof
DB_USER=postgres
DB_PASSWORD=postgres

# Secret Key
SECRET_KEY=your-secret-key
ACCESS_TOKEN_EXPIRE_MINUTES=3000

# LLM Configuration
LLM_TYPE=openai # options: openai, azure, ollama
LLM_API_VERSION=
LLM_API_KEY=
LLM_BASE_URL=https://api.openai.com/v1
LLM_MODEL=llama-3.3-70b-specdec

# OCR Configuration
AZURE_ENDPOINT=https://hunya.cognitiveservices.azure.com
AZURE_SUBSCRIPTION_KEY=your-azure-key
```

### Running with Docker
1. **Build and start the containers**
   ```sh
   docker-compose up --build -d
   ```

2. **Check running services**
   ```sh
   docker ps
   ```

### Running Locally (Development Mode)
1. **Install dependencies**
   ```sh
   pip install -r requirements.txt
   ```
2. **Set up the database**
   ```sh
   python -c 'from main import init_app; init_app()'
   ```
3. **Start the server**
   ```sh
   python main.py
   ```

## API Endpoints
### Authentication
- `POST /token` → Get JWT token

### Users
- `POST /users` → Create user
- `GET /users/me` → Get user details

### Verification
- `POST /verifications` → Create verification
- `GET /verifications` → List verifications
- `GET /verifications/{id}` → Get verification details
- `POST /verifications/{id}/upload` → Upload files for verification
- `GET /verifications/{id}/docx` → Download DOCX file
- `GET /verifications/{id}/image` → Download image file
- `GET /verifications/{id}/pdf` → Download PDF file
- `DELETE /verifications/{id}` → Delete verification

## Project Structure
```
.
├── main.py          # Flask application
├── llm.py           # LLM processing
├── ocr.py           # OCR text extraction
├── table.py         # Table detection in images
├── verify.py        # Document comparison logic
├── Dockerfile       # Docker setup
├── docker-compose.yml # Docker Compose configuration
├── requirements.txt # Python dependencies
└── .env             # Environment variables (excluded from repo)
```

## Contributors
- **Your Name** - Initial development

## License
This project is licensed under the MIT License.

