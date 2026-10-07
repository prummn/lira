"""Run browser tests against a disposable workspace, never the user's Library."""
from pathlib import Path
import os
import tempfile
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))

if __name__ == '__main__':
    # Browser tests must be deterministic and must not use personal model credentials.
    for name in list(os.environ):
        if name.startswith('PAPER_READER_MODEL_') or name == 'OPENAI_API_KEY':
            os.environ.pop(name, None)
    import fitz
    import uvicorn
    from app.main import create_app
    fixture_dir = ROOT / 'frontend' / 'test-artifacts'
    fixture_dir.mkdir(parents=True, exist_ok=True)
    document = fitz.open()
    page = document.new_page()
    page.insert_text((60, 65), 'Evidence Integration Test', fontsize=19)
    page.insert_text((60, 105), 'Abstract', fontsize=14)
    page.insert_textbox(fitz.Rect(60, 135, 530, 250), 'We study verifier-guided reasoning with local evidence. The problem is unreliable self-training feedback. Our method filters candidate reasoning traces with a verifier.', fontsize=12)
    page = document.new_page()
    page.insert_text((60, 65), 'Method', fontsize=14)
    page.insert_textbox(fitz.Rect(60, 105, 530, 220), 'Our method uses iterative verification. The verifier selects valid traces before supervised training. The experiment evaluates 100 examples and observes 72 correct answers.', fontsize=12)
    page.insert_text((60, 300), 'Limitations', fontsize=14)
    page.insert_textbox(fitz.Rect(60, 340, 530, 450), 'Our limitation is that verifier calibration depends on the evaluation domain. We do not claim that the method improves every dataset.', fontsize=12)
    document.save(fixture_dir / 'import-fixture.pdf')
    document.close()
    with tempfile.TemporaryDirectory(prefix='riw-browser-') as temporary:
        directory = Path(temporary)
        app = create_app('sqlite:///' + (directory / 'test.db').as_posix(), directory / 'pdfs')
        uvicorn.run(app, host='127.0.0.1', port=8010)
