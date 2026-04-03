# Nieves Observatory Data & Software Repository

This site provides a central repository for Nieves Observatory materials:

- Publications
- Datasets
- Software
- Gallery
- Contacts

## Upload Locations

Place files into these folders and they will appear automatically on the matching tab page:

- `content/publications` for PDF files and papers
- `content/datasets` for data files and images
- `content/software` for Python programs and notebooks
- `content/gallery` for image files

## Run Locally

1. Start the Flask server from the workspace root:
   - `python server.py`
2. Open:
   - `http://localhost:5000/repository/`

The server provides API endpoints used by the tab pages to list files dynamically.
