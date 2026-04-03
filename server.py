import os
from datetime import datetime, timezone

from flask import Flask, abort, jsonify, redirect, request, send_from_directory
from flask_cors import CORS
from werkzeug.utils import secure_filename

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
UPLOAD_FOLDER = os.path.join(BASE_DIR, 'uploads')
REPOSITORY_ROOT = os.path.join(BASE_DIR, 'Nieves_Observatory_Repository')
REPOSITORY_CONTENT_ROOT = os.path.join(REPOSITORY_ROOT, 'content')

ALLOWED_EXTENSIONS = {'doc', 'docx'}

SECTION_DIRS = {
    'publications': os.path.join(REPOSITORY_CONTENT_ROOT, 'publications'),
    'datasets': os.path.join(REPOSITORY_CONTENT_ROOT, 'datasets'),
    'software': os.path.join(REPOSITORY_CONTENT_ROOT, 'software'),
    'gallery': os.path.join(REPOSITORY_CONTENT_ROOT, 'gallery'),
}

SECTION_ALLOWED_EXTENSIONS = {
    'publications': {'pdf'},
    'datasets': {'fits', 'fit', 'fts', 'csv', 'txt', 'png', 'jpg', 'jpeg', 'webp', 'gif', 'zip'},
    'software': {'py', 'ipynb', 'txt', 'md', 'zip'},
    'gallery': {'png', 'jpg', 'jpeg', 'webp', 'gif'},
}

app = Flask(__name__)
CORS(app)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

for directory in SECTION_DIRS.values():
    os.makedirs(directory, exist_ok=True)


def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


def section_allowed_file(filename, section):
    if '.' not in filename:
        return False
    extension = filename.rsplit('.', 1)[1].lower()
    return extension in SECTION_ALLOWED_EXTENSIONS.get(section, set())


def list_section_files(section):
    directory = SECTION_DIRS.get(section)
    if directory is None:
        return None

    entries = []
    for filename in sorted(os.listdir(directory), key=str.lower):
        if filename.startswith('.'):
            continue

        filepath = os.path.join(directory, filename)
        if not os.path.isfile(filepath):
            continue

        stat = os.stat(filepath)
        entries.append(
            {
                'name': filename,
                'size': stat.st_size,
                'modified': datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(),
                'url': f'/repository/files/{section}/{filename}',
            }
        )

    return entries


@app.route('/upload', methods=['POST'])
def upload_file():
    if 'file' not in request.files:
        return jsonify({'error': 'No file part'}), 400

    file = request.files['file']
    section = request.form.get('section')

    if file.filename == '':
        return jsonify({'error': 'Invalid file'}), 400

    filename = secure_filename(file.filename)

    if section:
        if section not in SECTION_DIRS:
            return jsonify({'error': 'Invalid section'}), 400
        if not section_allowed_file(filename, section):
            return jsonify({'error': 'Invalid file type for section'}), 400

        filepath = os.path.join(SECTION_DIRS[section], filename)
        file.save(filepath)
        return jsonify({'success': True, 'section': section, 'filename': filename})

    if not allowed_file(filename):
        return jsonify({'error': 'Invalid file'}), 400

    filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
    file.save(filepath)
    return jsonify({'success': True, 'filename': filename})


@app.route('/api/repository/list/<section>', methods=['GET'])
def api_list_repository_section(section):
    files = list_section_files(section)
    if files is None:
        return jsonify({'error': 'Unknown section'}), 404

    return jsonify({'section': section, 'files': files})


@app.route('/repository/files/<section>/<path:filename>', methods=['GET'])
def repository_file(section, filename):
    directory = SECTION_DIRS.get(section)
    if directory is None:
        abort(404)

    safe_name = secure_filename(filename)
    file_path = os.path.join(directory, safe_name)
    if not os.path.isfile(file_path):
        abort(404)

    return send_from_directory(directory, safe_name)


@app.route('/repository/', methods=['GET'])
def repository_home():
    return send_from_directory(REPOSITORY_ROOT, 'index.html')


@app.route('/', methods=['GET'])
def root_home():
    return redirect('/repository/')


@app.route('/repository/<path:path>', methods=['GET'])
def repository_static(path):
    safe_path = os.path.normpath(path)
    if safe_path.startswith('..'):
        abort(404)

    full_path = os.path.join(REPOSITORY_ROOT, safe_path)
    if not os.path.isfile(full_path):
        abort(404)

    return send_from_directory(REPOSITORY_ROOT, safe_path)


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
