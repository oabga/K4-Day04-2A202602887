import unittest

from app import PROVIDER_NAME, SYSTEM_PROMPT_PATH, TOOLS_PATH, new_transcript
from streamlit.testing.v1 import AppTest
from tools import TOOL_FUNCTIONS, load_tool_declarations
from versioning import build_artifact_version


class AppTranscriptTest(unittest.TestCase):
    def test_transcript_keeps_runtime_evidence(self) -> None:
        artifact = build_artifact_version('v0', SYSTEM_PROMPT_PATH, TOOLS_PATH)
        transcript, path = new_transcript('v0', 'test/model', artifact)

        self.assertEqual(transcript['provider'], PROVIDER_NAME)
        self.assertEqual(transcript['artifact_version'], artifact.artifact_version)
        self.assertEqual(transcript['model'], 'test/model')
        self.assertTrue(path.name.endswith('.transcript.json'))

    def test_page_loads_without_calling_provider(self) -> None:
        page = AppTest.from_file('app.py').run()

        self.assertFalse(page.exception)
        self.assertEqual(page.title[0].value, 'IT Helpdesk Agent')

    def test_ui_tools_match_registry(self) -> None:
        declared = {item['name'] for item in load_tool_declarations(TOOLS_PATH)}

        self.assertEqual(declared, set(TOOL_FUNCTIONS))
        self.assertEqual(
            TOOL_FUNCTIONS['create_ticket']('dry run', 'low', 'LT-204', False)['status'],
            'needs_confirmation',
        )
        self.assertEqual(
            TOOL_FUNCTIONS['search_device_info']('Lenovo', 'LT-318', 'drivers', 2)['error'],
            'restricted_internal_identifier',
        )


if __name__ == '__main__':
    unittest.main()
