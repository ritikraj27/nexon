#!/bin/bash
# setup_nexon.sh
# ============================================================
# NEXON Complete Setup Script
# Run once after cloning: bash setup_nexon.sh
# ============================================================

echo "⬡ NEXON Setup Script"
echo "===================="

# ── Step 1: Python dependencies ──────────────────────────────
echo ""
echo "📦 Installing Python dependencies..."
pip install \
  fastapi==0.111.0 \
  uvicorn[standard]==0.29.0 \
  sqlalchemy==2.0.30 \
  python-multipart==0.0.9 \
  pydantic==2.7.1 \
  python-dotenv==1.0.1 \
  aiofiles==23.2.1 \
  httpx==0.27.0 \
  requests==2.31.0 \
  openai-whisper==20231117 \
  pyttsx3==2.90 \
  librosa==0.10.1 \
  numpy==1.26.4 \
  soundfile==0.12.1 \
  sentence-transformers==2.7.0 \
  python-docx==1.1.2 \
  reportlab==4.1.0 \
  openpyxl==3.1.2 \
  PyPDF2==3.0.1 \
  Pillow==10.3.0 \
  pytesseract==0.3.10 \
  pandas==2.2.2 \
  matplotlib==3.9.0 \
  beautifulsoup4==4.12.3 \
  playwright==1.44.0 \
  pyautogui==0.9.54 \
  pyperclip==1.8.2 \
  psutil==5.9.8

echo "✅ Python packages installed"

# ── Step 2: Playwright browsers ──────────────────────────────
echo ""
echo "🌐 Installing Playwright browser (for web automation)..."
playwright install chromium
echo "✅ Playwright ready"

# ── Step 3: Tesseract OCR ─────────────────────────────────────
echo ""
echo "🔍 Installing Tesseract OCR (for screen reading)..."
if [[ "$OSTYPE" == "darwin"* ]]; then
  if command -v brew &> /dev/null; then
    brew install tesseract
    echo "✅ Tesseract installed via Homebrew"
  else
    echo "⚠️  Homebrew not found. Install from: https://brew.sh"
    echo "   Then run: brew install tesseract"
  fi
elif [[ "$OSTYPE" == "linux-gnu"* ]]; then
  sudo apt-get install -y tesseract-ocr
  echo "✅ Tesseract installed"
fi

# ── Step 4: Node.js dependencies ─────────────────────────────
echo ""
echo "📦 Installing Node.js dependencies (Electron)..."
npm install
echo "✅ Node packages installed"

# ── Step 5: Database migration ────────────────────────────────
echo ""
echo "🗄️  Running database migration..."
python migrate_db.py
echo "✅ Database ready"

# ── Step 6: macOS permissions reminder ───────────────────────
if [[ "$OSTYPE" == "darwin"* ]]; then
  echo ""
  echo "⚠️  macOS PERMISSIONS REQUIRED:"
  echo "   Open: System Preferences → Privacy & Security"
  echo "   Enable for Terminal and/or Python:"
  echo "   ✓ Microphone"
  echo "   ✓ Camera"
  echo "   ✓ Screen Recording"
  echo "   ✓ Accessibility"
  echo ""
  echo "   Opening System Preferences..."
  open "x-apple.systempreferences:com.apple.preference.security?Privacy"
fi

# ── Step 7: Create .env if missing ───────────────────────────
if [ ! -f ".env" ]; then
  echo ""
  echo "📝 Creating .env file from template..."
  cp .env.template .env
  echo "✅ .env created — edit it to add your API keys"
else
  echo "✅ .env already exists"
fi

# ── Step 8: Pull Ollama model ─────────────────────────────────
echo ""
echo "🤖 Pulling Ollama model (llama3.2:3b)..."
if command -v ollama &> /dev/null; then
  ollama pull llama3.2:3b
  echo "✅ Ollama model ready"
else
  echo "⚠️  Ollama not installed."
  echo "   Download from: https://ollama.com"
  echo "   Then run: ollama pull llama3.2:3b"
fi

echo ""
echo "════════════════════════════════════"
echo "✅ NEXON setup complete!"
echo ""
echo "To start NEXON:"
echo "  Terminal 1: uvicorn backend.main:app --host 127.0.0.1 --port 8000 --reload"
echo "  Terminal 2: npm start"
echo ""
echo "To enroll your face:"
echo "  Open face_enrollment.html in Chrome while backend is running"
echo "════════════════════════════════════"