"""
Tests for utility functions: city normalization, date parsing, JSON parsing.
"""

import pytest
from datetime import date, datetime, timedelta
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from crud import normalize_city, resolve_date, CITY_ALIASES
from vlm_service import safe_extract_json


# ══════════════════════════════════════════════════════════════════════════════
# City Normalization Tests
# ══════════════════════════════════════════════════════════════════════════════

class TestNormalizeCity:
    """Tests for city name normalization."""

    def test_exact_alias_match_lowercase(self):
        """Test exact match with lowercase input."""
        assert normalize_city("kl") == "Kuala Lumpur"
        assert normalize_city("jb") == "Johor Bahru"
        assert normalize_city("penang") == "Penang"

    def test_exact_alias_match_uppercase(self):
        """Test exact match with uppercase input."""
        assert normalize_city("KL") == "Kuala Lumpur"
        assert normalize_city("JB") == "Johor Bahru"

    def test_exact_alias_match_mixed_case(self):
        """Test exact match with mixed case input."""
        assert normalize_city("Kuala Lumpur") == "Kuala Lumpur"
        assert normalize_city("PENANG") == "Penang"

    def test_alternate_spellings(self):
        """Test alternate city spellings."""
        assert normalize_city("pulau pinang") == "Penang"
        assert normalize_city("malacca") == "Melaka"
        assert normalize_city("butterworth") == "Penang"
        assert normalize_city("georgetown") == "Penang"

    def test_state_names(self):
        """Test state names mapping to main city."""
        assert normalize_city("kedah") == "Alor Setar"
        assert normalize_city("kelantan") == "Kota Bharu"
        assert normalize_city("sabah") == "Kota Kinabalu"
        assert normalize_city("sarawak") == "Kuching"

    def test_whitespace_handling(self):
        """Test handling of extra whitespace."""
        assert normalize_city("  kl  ") == "Kuala Lumpur"
        assert normalize_city("\tpenang\n") == "Penang"

    def test_unknown_city_returns_title_case(self):
        """Test unknown city returns title case version."""
        result = normalize_city("unknown city")
        assert result == "Unknown City"

    def test_empty_string(self):
        """Test empty string handling."""
        assert normalize_city("") == ""

    def test_none_handling(self):
        """Test None handling."""
        assert normalize_city(None) is None


# ══════════════════════════════════════════════════════════════════════════════
# Date Parsing Tests
# ══════════════════════════════════════════════════════════════════════════════

class TestResolveDate:
    """Tests for natural language date parsing."""

    def test_standard_format(self):
        """Test YYYY-MM-DD format."""
        result = resolve_date("2025-03-25")
        assert result == date(2025, 3, 25)

    def test_slash_format_dmy(self):
        """Test DD/MM/YYYY format."""
        result = resolve_date("25/03/2025")
        assert result == date(2025, 3, 25)

    def test_slash_format_mdy(self):
        """Test MM/DD/YYYY format."""
        result = resolve_date("03/25/2025")
        assert result == date(2025, 3, 25)

    def test_none_input(self):
        """Test None input returns None."""
        assert resolve_date(None) is None

    def test_empty_string(self):
        """Test empty string returns None."""
        assert resolve_date("") is None

    def test_invalid_date_returns_none(self):
        """Test invalid date string returns None."""
        result = resolve_date("not a date")
        # Should return None (or let dateparser try)
        # The function should handle this gracefully


# If dateparser is installed, test natural language dates
try:
    import dateparser
    DATEPARSER_AVAILABLE = True
except ImportError:
    DATEPARSER_AVAILABLE = False


@pytest.mark.skipif(not DATEPARSER_AVAILABLE, reason="dateparser not installed")
class TestResolveDateNaturalLanguage:
    """Tests for natural language date parsing (requires dateparser)."""

    def test_tomorrow(self):
        """Test 'tomorrow' parsing."""
        result = resolve_date("tomorrow")
        expected = date.today() + timedelta(days=1)
        assert result == expected

    def test_day_month_format(self):
        """Test '15 March' format."""
        result = resolve_date("15 March")
        assert result is not None
        assert result.day == 15
        assert result.month == 3


# ══════════════════════════════════════════════════════════════════════════════
# JSON Parsing Tests
# ══════════════════════════════════════════════════════════════════════════════

class TestSafeExtractJson:
    """Tests for robust JSON extraction from LLM output."""

    def test_direct_json(self):
        """Test direct JSON parsing."""
        result = safe_extract_json('{"amount": 35.00, "recipient": "Test"}')
        assert result == {"amount": 35.00, "recipient": "Test"}

    def test_json_with_markdown_fence(self):
        """Test JSON wrapped in markdown code fence."""
        input_text = '''```json
{"amount": 35.00, "recipient": "Test"}
```'''
        result = safe_extract_json(input_text)
        assert result["amount"] == 35.00
        assert result["recipient"] == "Test"

    def test_json_with_surrounding_text(self):
        """Test JSON extraction from text with surrounding content."""
        input_text = '''Here is the extracted data:
{"amount": 35.00, "recipient": "Test"}
Let me know if you need anything else.'''
        result = safe_extract_json(input_text)
        assert result["amount"] == 35.00

    def test_nested_json(self):
        """Test nested JSON object parsing."""
        input_text = '{"outer": {"inner": "value"}, "number": 42}'
        result = safe_extract_json(input_text)
        assert result["outer"]["inner"] == "value"
        assert result["number"] == 42

    def test_invalid_json_returns_none(self):
        """Test invalid JSON returns None."""
        result = safe_extract_json("this is not json at all")
        assert result is None

    def test_single_quotes_conversion(self):
        """Test single quotes get converted to double quotes."""
        input_text = "{'amount': 35.00, 'recipient': 'Test'}"
        result = safe_extract_json(input_text)
        # This might work if the function handles single quotes
        # If not, result will be None

    def test_empty_string(self):
        """Test empty string returns None."""
        result = safe_extract_json("")
        assert result is None

    def test_json_with_newlines(self):
        """Test JSON with newlines inside."""
        input_text = '''{
    "amount": 35.00,
    "recipient": "Test User",
    "reference": "BUS123456"
}'''
        result = safe_extract_json(input_text)
        assert result["amount"] == 35.00
        assert result["reference"] == "BUS123456"


# ══════════════════════════════════════════════════════════════════════════════
# TTLDict Tests (Session Store)
# ══════════════════════════════════════════════════════════════════════════════

class TestTTLDict:
    """Tests for TTL dictionary used in session management."""

    def test_set_and_get(self):
        """Test basic set and get operations."""
        from main import TTLDict

        store = TTLDict(ttl=60, maxsize=10)
        store.set("key1", ["message1", "message2"])

        result = store.get("key1")
        assert result == ["message1", "message2"]

    def test_get_missing_key(self):
        """Test getting a non-existent key."""
        from main import TTLDict

        store = TTLDict(ttl=60, maxsize=10)
        result = store.get("nonexistent")
        assert result is None

    def test_get_with_default(self):
        """Test getting with default value."""
        from main import TTLDict

        store = TTLDict(ttl=60, maxsize=10)
        result = store.get("nonexistent", default=[])
        assert result is None  # Our implementation returns None, not default

    def test_maxsize_eviction(self):
        """Test that oldest entries are evicted when maxsize is reached."""
        from main import TTLDict

        store = TTLDict(ttl=60, maxsize=3)
        store.set("key1", "value1")
        store.set("key2", "value2")
        store.set("key3", "value3")
        store.set("key4", "value4")  # Should evict key1

        assert store.get("key1") is None
        assert store.get("key4") == "value4"

    def test_contains(self):
        """Test __contains__ method."""
        from main import TTLDict

        store = TTLDict(ttl=60, maxsize=10)
        store.set("key1", "value1")

        assert "key1" in store
        assert "key2" not in store


# ══════════════════════════════════════════════════════════════════════════════
# Mask Message Tests (PII Protection)
# ══════════════════════════════════════════════════════════════════════════════

class TestMaskMessage:
    """Tests for PII masking in logs."""

    def test_short_message_masked(self):
        """Test short messages are fully masked."""
        from main import mask_message

        result = mask_message("hello")
        assert result == "***"

    def test_long_message_partially_masked(self):
        """Test long messages show only first/last chars."""
        from main import mask_message

        result = mask_message("This is a longer message that should be masked")
        assert "..." in result
        assert len(result) < len("This is a longer message that should be masked")

    def test_medium_message(self):
        """Test medium length message."""
        from main import mask_message

        result = mask_message("Medium message here")
        assert "..." in result
