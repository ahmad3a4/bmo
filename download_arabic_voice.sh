#!/usr/bin/env bash
# Download Arabic Piper TTS voice model for BMO
# Run this script once from the /home/ahmad/aria directory

VOICES_DIR="$(dirname "$0")/voices"
MODEL_NAME="ar_JO-kareem-low"
ONNX_URL="https://huggingface.co/rhasspy/piper-voices/resolve/main/ar/ar_JO/kareem/low/ar_JO-kareem-low.onnx"
ONNX_OUT="$VOICES_DIR/$MODEL_NAME.onnx"

echo "🔊 Downloading Arabic (ar_JO-kareem-low) Piper voice model..."
echo "   Target: $ONNX_OUT"

# Compare against the server's real size: a "bigger than 1 MB" check once let a
# download cut off at 8 MB (of ~60 MB) pass as valid, and Piper couldn't load it.
EXPECTED=$(curl -sIL "$ONNX_URL" | grep -i '^content-length' | tail -1 | tr -dc '0-9')
if [ -f "$ONNX_OUT" ] && [ -n "$EXPECTED" ] && [ "$(stat -c%s "$ONNX_OUT" 2>/dev/null)" = "$EXPECTED" ]; then
    echo "✅ ONNX model already exists and is complete."
else
    echo "⬇️  Downloading ONNX (~60MB)..."
    wget -q --show-progress -O "$ONNX_OUT" "$ONNX_URL"
    if [ $? -eq 0 ]; then
        echo "✅ Download complete: $ONNX_OUT"
    else
        echo "❌ Download failed. Trying curl..."
        curl -L -o "$ONNX_OUT" "$ONNX_URL" && echo "✅ Done via curl." || echo "❌ Failed."
    fi
fi

# Verify the JSON config is there too
JSON_OUT="$VOICES_DIR/$MODEL_NAME.onnx.json"
if [ -f "$JSON_OUT" ]; then
    echo "✅ JSON config already present: $JSON_OUT"
else
    echo "⬇️  Downloading JSON config..."
    wget -q -O "$JSON_OUT" "https://huggingface.co/rhasspy/piper-voices/resolve/main/ar/ar_JO/kareem/low/ar_JO-kareem-low.onnx.json" \
        && echo "✅ JSON config downloaded." \
        || echo "❌ JSON download failed."
fi

echo ""
echo "Files in voices/:"
ls -lh "$VOICES_DIR/"
echo ""
echo "✅ Setup complete! Restart BMO to speak Arabic."
