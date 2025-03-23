from flask import Flask, render_template, request, jsonify
import os
import backend as bk


app = Flask(
    __name__, 
    template_folder="Frontend/",
    static_folder="Frontend/"
)
app.config['UPLOAD_FOLDER'] = 'uploads'

# Ensure upload directory exists
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/upload', methods=['POST'])
def upload():
    # message = request.form.get('message')
    file = request.files.get('file')
    
    if file:
        filename = os.path.join(app.config['UPLOAD_FOLDER'], file.filename)
        file.save(filename)
        print(f"File saved to: {filename}")
    
    # print(f"Received message: {message}")
    return jsonify({
        'status': 'success',
        'file': file.filename if file else None
    })

@app.route('/analyze', methods=['POST'])
def analyze():
    data = request.get_json()  # ✅ Get JSON data properly
    text = data.get("text", "")  # ✅ Extract text safely

    if not text:
        return jsonify({"status": "error", "message": "No text provided"}), 400
    
    print(text, type(text))
    entities = bk.extract_entities(text)

    return jsonify({
        'status': 'success',
        'entities': entities
    }), 200

if __name__ == '__main__':
    app.run(debug=True)