import unittest
from unittest.mock import Mock

from youtube_automation.gemini import browser as gemini_browser


class GeminiNewChatTests(unittest.TestCase):
    def test_start_new_gemini_chat_goes_to_home_and_starts_fresh_conversation(self):
        page = Mock()
        gemini_browser.start_new_gemini_chat(page, 7)

        page.goto.assert_called_once_with(
            gemini_browser.config.GEMINI_URL,
            wait_until="domcontentloaded",
            timeout=60000,
        )
        page.get_by_role.assert_any_call(
            "button",
            name=gemini_browser.re.compile("new chat|new conversation", gemini_browser.re.IGNORECASE),
        )


if __name__ == "__main__":
    unittest.main()
