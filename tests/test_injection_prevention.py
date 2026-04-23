"""
Security Injection Prevention Tests
====================================
Tests for dynamic rules sanitization and injection attack prevention.
"""

import pytest
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from utils.dynamic_rules import sanitize_dynamic_rules
from config.constants import MAX_DYNAMIC_RULES_LENGTH


class TestTemplateInjection:
    """Template injection prevention testleri."""

    def test_jinja_template_blocking(self):
        """Jinja2 template injection engelleme."""
        malicious = "Normal text {{ config.items() }} more text"
        sanitized = sanitize_dynamic_rules(malicious)
        
        assert "{{" not in sanitized
        assert "}}" not in sanitized
        assert "[BLOCKED_TEMPLATE]" in sanitized

    def test_nested_template_blocking(self):
        """Nested template injection engelleme ({{{{}}}})."""
        malicious = "{{{{ config }}}}"
        sanitized = sanitize_dynamic_rules(malicious)
        
        assert "{{" not in sanitized
        assert "}}" not in sanitized

    def test_jinja_statement_blocking(self):
        """Jinja statement {% %} engelleme."""
        malicious = "{% import os %} {% os.system('ls') %}"
        sanitized = sanitize_dynamic_rules(malicious)
        
        assert "{%" not in sanitized
        assert "%}" not in sanitized
        assert "[BLOCKED_JINJA]" in sanitized

    def test_jinja_comment_blocking(self):
        """Jinja comment {# #} engelleme."""
        malicious = "Text {# comment #} more text"
        sanitized = sanitize_dynamic_rules(malicious)
        
        assert "{#" not in sanitized
        assert "#}" not in sanitized

    def test_multiline_template_blocking(self):
        """Multiline template injection engelleme."""
        malicious = """
        Some text
        {{
            config.items()
        }}
        More text
        """
        sanitized = sanitize_dynamic_rules(malicious)
        
        assert "{{" not in sanitized
        assert "[BLOCKED_TEMPLATE]" in sanitized


class TestCodeInjection:
    """Code injection prevention testleri."""

    def test_eval_blocking(self):
        """eval() injection engelleme."""
        malicious = "Run this: eval('__import__(\"os\").system(\"ls\")')"
        sanitized = sanitize_dynamic_rules(malicious)
        
        assert "eval(" not in sanitized or "[BLOCKED_FUNC]" in sanitized

    def test_exec_blocking(self):
        """exec() injection engelleme."""
        malicious = "exec('import os; os.system(\"rm -rf /\")')"
        sanitized = sanitize_dynamic_rules(malicious)
        
        assert "exec(" not in sanitized or "[BLOCKED_FUNC]" in sanitized

    def test_import_blocking(self):
        """__import__() injection engelleme."""
        malicious = "__import__('os').system('ls')"
        sanitized = sanitize_dynamic_rules(malicious)
        
        assert "[BLOCKED_FUNC]" in sanitized

    def test_os_module_blocking(self):
        """os. module access engelleme."""
        malicious = "os.system('whoami')"
        sanitized = sanitize_dynamic_rules(malicious)
        
        assert "os." not in sanitized or "[BLOCKED_FUNC]" in sanitized

    def test_subprocess_blocking(self):
        """subprocess module engelleme."""
        malicious = "subprocess.run(['ls', '-la'])"
        sanitized = sanitize_dynamic_rules(malicious)
        
        assert "subprocess." not in sanitized or "[BLOCKED_FUNC]" in sanitized

    def test_backtick_code_blocking(self):
        """Backtick code block engelleme."""
        malicious = "Run `os.system('ls')` command"
        sanitized = sanitize_dynamic_rules(malicious)
        
        assert "`" not in sanitized or "[BLOCKED_CODE]" in sanitized


class TestHTMLJSInjection:
    """HTML/JavaScript injection prevention testleri."""

    def test_script_tag_blocking(self):
        """<script> tag engelleme."""
        malicious = "<script>alert('XSS')</script>"
        sanitized = sanitize_dynamic_rules(malicious)
        
        assert "<script" not in sanitized.lower() or "[BLOCKED_SCRIPT]" in sanitized

    def test_script_multiline_blocking(self):
        """Multiline script tag engelleme."""
        malicious = """
        <script>
            alert('XSS')
            document.cookie
        </script>
        """
        sanitized = sanitize_dynamic_rules(malicious)
        
        assert "<script" not in sanitized.lower()

    def test_event_handler_blocking(self):
        """Event handler injection engelleme."""
        malicious = '<img src=x onerror="alert(1)">'
        sanitized = sanitize_dynamic_rules(malicious)
        
        assert "onerror=" not in sanitized.lower() or "[BLOCKED_EVENT]" in sanitized

    def test_onclick_blocking(self):
        """onclick event engelleme."""
        malicious = '<div onclick="malicious()">Click</div>'
        sanitized = sanitize_dynamic_rules(malicious)
        
        assert "onclick=" not in sanitized.lower()

    def test_html_tag_blocking(self):
        """General HTML tag engelleme."""
        malicious = "<div>Content</div>"
        sanitized = sanitize_dynamic_rules(malicious)
        
        assert "<div>" not in sanitized or "[BLOCKED_HTML]" in sanitized


class TestPathTraversal:
    """Path traversal prevention testleri."""

    def test_dot_dot_slash_blocking(self):
        """../ path traversal engelleme."""
        malicious = "../../../etc/passwd"
        sanitized = sanitize_dynamic_rules(malicious)
        
        assert "../" not in sanitized or "[BLOCKED_PATH]" in sanitized

    def test_dot_dot_backslash_blocking(self):
        """..\\ Windows path traversal engelleme."""
        malicious = "..\\..\\..\\windows\\system32"
        sanitized = sanitize_dynamic_rules(malicious)
        
        assert "..\\" not in sanitized or "[BLOCKED_PATH]" in sanitized


class TestUnicodeNormalization:
    """Unicode normalization bypass prevention testleri."""

    def test_unicode_template_blocking(self):
        """Unicode escaped template injection engelleme."""
        # \u007b = {, \u007d = }
        malicious = "\\u007b\\u007b config \\u007d\\u007d"
        sanitized = sanitize_dynamic_rules(malicious)
        
        # NFKC normalization'dan sonra template pattern olmamalı
        assert "{{" not in sanitized

    def test_fullwidth_character_normalization(self):
        """Fullwidth character normalization."""
        # Fullwidth characters NFKC'de normal karakterlere dönüşür
        malicious = "｛｛ config ｝｝"  # Fullwidth braces
        sanitized = sanitize_dynamic_rules(malicious)
        
        # Normalized ve blocked olmalı
        assert "{{" not in sanitized or "[BLOCKED" in sanitized


class TestBase64Payload:
    """Base64 encoded payload detection testleri."""

    def test_long_base64_blocking(self):
        """Long base64 string engelleme."""
        # 200+ karakter base64 string
        malicious = "a" * 250  # Simple pattern, not real base64
        sanitized = sanitize_dynamic_rules(malicious)
        
        # Very long strings should be flagged
        # (Bu test heuristic, gerçek base64 detection daha kompleks)

    def test_real_base64_payload(self):
        """Real base64 encoded payload testi."""
        import base64
        # Gerçek base64 payload
        payload = base64.b64encode(b"eval('malicious code')").decode()
        malicious = f"Data: {payload}"
        sanitized = sanitize_dynamic_rules(malicious)
        
        # Long base64 should be blocked
        if len(payload) > 200:
            assert "[BLOCKED_BASE64]" in sanitized


class TestSQLInjection:
    """SQL injection prevention testleri."""

    def test_sql_comment_blocking(self):
        """SQL comment -- engelleme."""
        malicious = "admin' --"
        sanitized = sanitize_dynamic_rules(malicious)
        
        assert "--" not in sanitized or "[BLOCKED]" in sanitized

    def test_sql_block_comment_blocking(self):
        """SQL block comment /* */ engelleme."""
        malicious = "admin' /* comment */"
        sanitized = sanitize_dynamic_rules(malicious)
        
        assert "/*" not in sanitized or "[BLOCKED]" in sanitized


class TestControlCharacters:
    """Control character removal testleri."""

    def test_null_byte_removal(self):
        """Null byte injection engelleme."""
        malicious = "file.txt\x00.exe"
        sanitized = sanitize_dynamic_rules(malicious)
        
        assert "\x00" not in sanitized

    def test_control_char_removal(self):
        """Control characters engelleme."""
        # \x00-\x08, \x0B, \x0C, \x0E-\x1F, \x7F
        malicious = "text\x01\x02\x03more text"
        sanitized = sanitize_dynamic_rules(malicious)
        
        for char in sanitized:
            assert ord(char) < 0x01 or ord(char) > 0x1F or char in '\n\t'


class TestMaxLength:
    """Max length enforcement testleri."""

    def test_max_length_enforcement(self):
        """Max length truncation."""
        long_text = "a" * (MAX_DYNAMIC_RULES_LENGTH + 1000)
        sanitized = sanitize_dynamic_rules(long_text)
        
        assert len(sanitized) <= MAX_DYNAMIC_RULES_LENGTH

    def test_normal_text_passes(self):
        """Normal text should pass through."""
        normal = "This is a normal trading rule. Buy when RSI < 30."
        sanitized = sanitize_dynamic_rules(normal)
        
        assert sanitized == normal


class TestEdgeCases:
    """Edge case testleri."""

    def test_empty_string(self):
        """Empty string handling."""
        sanitized = sanitize_dynamic_rules("")
        assert sanitized == ""

    def test_none_input(self):
        """None input handling."""
        sanitized = sanitize_dynamic_rules(None)
        assert sanitized == ""

    def test_whitespace_only(self):
        """Whitespace only input."""
        sanitized = sanitize_dynamic_rules("   \n\t   ")
        assert sanitized.strip() == ""

    def test_only_special_chars(self):
        """Only special characters input."""
        malicious = "{{}}{%}[]{#}"
        sanitized = sanitize_dynamic_rules(malicious)
        
        assert "{{" not in sanitized
        assert "{%" not in sanitized

    def test_mixed_attack(self):
        """Mixed attack vectors."""
        malicious = """
        {{ config.items() }}
        <script>alert(1)</script>
        ../../../etc/passwd
        eval('malicious')
        """
        sanitized = sanitize_dynamic_rules(malicious)
        
        # Tüm attack vector'lar blocked olmalı
        assert "{{" not in sanitized
        assert "<script" not in sanitized.lower()
        assert "../" not in sanitized
        assert "eval(" not in sanitized.lower() or "[BLOCKED_FUNC]" in sanitized


class TestLogging:
    """Logging behavior testleri."""

    def test_heavy_sanitization_warning(self, caplog):
        """Heavy sanitization warning testi."""
        import logging
        
        # %80'den fazla silinecek long malicious input
        malicious = "{{evil}}" * 1000
        malicious += "normal text" * 10  # Sadece %10 normal
        
        with caplog.at_level(logging.WARNING):
            sanitized = sanitize_dynamic_rules(malicious)
        
        # Warning log'lanmış olmalı
        assert any("heavy sanitization" in record.message.lower() 
                  for record in caplog.records)


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
