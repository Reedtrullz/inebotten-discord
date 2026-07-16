#!/usr/bin/env python3
"""
Calculator & Unit Converter Manager for Inebotten
Performs calculations and unit conversions
"""

import re
from simpleeval import simple_eval, InvalidExpression


_LEADING_INVOCATION = re.compile(
    r"^\s*(?:@inebotten\b|<@!?\d+>)\s*[:,;-]?\s*",
    re.IGNORECASE,
)
_POLITE_PREFIX = re.compile(
    r"^(?:(?:kan|kunne|vil)\s+du|(?:can|could|would|will)\s+you|"
    r"vennligst|vær\s+så\s+snill|ver\s+så\s+snill|please)\s*,?\s+",
    re.IGNORECASE,
)
_NON_REQUEST_PATTERNS = (
    re.compile(r"\b(?:ikke|ikkje|not|never|don['’]t|do\s+not)\b", re.IGNORECASE),
    re.compile(
        r"^(?:jeg|eg|æ)\s+(?:sa|skrev|skreiv|leste|las)\b|"
        r"^i\s+(?:said|wrote|read)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"^(?:hva\s+skjer\s+hvis|kva\s+skjer\s+om|ka\s+skjer\s+hvis|"
        r"what\s+happens\s+if|hvis|om|if)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"^(?:eksempel|example|hva\s+betyr|kva\s+tyder|hvordan\s+skriver|"
        r"korleis\s+skriv|how\s+do\s+i\s+(?:say|write)|"
        r"what\s+does\b.*\bmean)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"^(?:jeg|eg|æ)\s+(?:vurderer|tenker\s+på)\b|"
        r"^i(?:'m|\s+am)\s+(?:considering|thinking\s+about)\b",
        re.IGNORECASE,
    ),
)
_TRAILING_POLITENESS = re.compile(
    r"\s*,?\s*(?:takk(?:\s+skal\s+du\s+ha)?|tusen\s+takk|"
    r"please|thanks|thank\s+you)\s*[?!.]*$",
    re.IGNORECASE,
)
_LEADING_COURTESY_REQUEST = re.compile(
    r"^(?:(?:(?:kan|kunne|vil)\s+du|(?:can|could|would|will)\s+you|"
    r"vennligst|vær\s+så\s+snill|ver\s+så\s+snill|please)\s*,?\s*"
    r"(?:(?:om|hvis|viss)\s+du\s+(?:kan|har\s+tid)|"
    r"if\s+you\s+(?:can|have\s+(?:time|a\s+moment))|"
    r"when\s+you\s+have\s+(?:time|a\s+moment))|"
    r"(?:(?:om|hvis|viss)\s+du\s+(?:kan|har\s+tid)|"
    r"if\s+you\s+(?:can|have\s+(?:time|a\s+moment))|"
    r"when\s+you\s+have\s+(?:time|a\s+moment))\s*,?\s*"
    r"(?:(?:kan|kunne|vil)\s+du|(?:can|could|would|will)\s+you|"
    r"vennligst|vær\s+så\s+snill|ver\s+så\s+snill|please))\s*,?\s*",
    re.IGNORECASE,
)
_TRAILING_COURTESY = re.compile(
    r"(?:\s*,\s*|\s+)(?:(?:om|hvis|viss)\s+du\s+kan|"
    r"(?:om|hvis|viss)\s+du\s+har\s+tid|når\s+du\s+har\s+tid|"
    r"if\s+you\s+can|if\s+you\s+have\s+(?:time|a\s+moment)|"
    r"when\s+you\s+have\s+(?:time|a\s+moment))\s*[?!.]*$",
    re.IGNORECASE,
)
_MATH_EXPRESSION = re.compile(r"[\d+\-*/xX×:,().\s]+")
_QUESTION_MATH_OPERATOR = re.compile(
    r"(?:[\d)]\s*[+*/xX×]\s*[-+(\d]|[\d)]\s*-\s*[-+(\d])"
)
_DATE_LIKE_EXPRESSION = re.compile(
    r"(?<!\d)(?:"
    r"(?:19|20|21)\d{2}(?P<ymd_separator>[./-])"
    r"(?:0?[1-9]|1[0-2])(?P=ymd_separator)"
    r"(?:0?[1-9]|[12]\d|3[01])|"
    r"(?:0?[1-9]|[12]\d|3[01])(?P<dmy_separator>[./-])"
    r"(?:0?[1-9]|1[0-2])(?P=dmy_separator)"
    r"(?:\d{2}|(?:19|20|21)\d{2})|"
    r"(?:0?[1-9]|1[0-2])(?P<mdy_separator>[./-])"
    r"(?:0?[1-9]|[12]\d|3[01])(?P=mdy_separator)"
    r"(?:\d{2}|(?:19|20|21)\d{2})"
    r")(?!\d)"
)


def _prepare_calculator_request(message_content):
    if not isinstance(message_content, str):
        return None
    content = _LEADING_INVOCATION.sub("", message_content, count=1).strip()
    content = _LEADING_COURTESY_REQUEST.sub("", content, count=1).strip()
    content = _TRAILING_POLITENESS.sub("", content).strip()
    content = _TRAILING_COURTESY.sub("", content).strip()
    if not content or any(pattern.search(content) for pattern in _NON_REQUEST_PATTERNS):
        return None
    content = _POLITE_PREFIX.sub("", content, count=1).strip()
    if any(pattern.search(content) for pattern in _NON_REQUEST_PATTERNS):
        return None
    content = _TRAILING_POLITENESS.sub("", content).strip()
    content = re.sub(r"\bwhat['’]s\b", "what is", content, flags=re.IGNORECASE)
    return content.rstrip("?!.").strip()


class CalculatorManager:
    """
    Handles calculations and unit conversions
    """

    def __init__(self):
        # Exchange rates (approximate - would use real API in production)
        self.exchange_rates = {
            "usd": {"nok": 10.85, "eur": 0.92, "gbp": 0.79},
            "nok": {"usd": 0.092, "eur": 0.085, "gbp": 0.073},
            "eur": {"nok": 11.78, "usd": 1.09, "gbp": 0.86},
            "gbp": {"nok": 13.71, "usd": 1.27, "eur": 1.17},
            "btc": {"usd": 67420, "nok": 731000},
        }

        # Temperature conversions
        self.temp_units = ["c", "celsius", "f", "fahrenheit", "k", "kelvin"]

        # Length conversions (to meters)
        self.length_units = {
            "m": 1,
            "meter": 1,
            "meters": 1,
            "metre": 1,
            "km": 1000,
            "kilometer": 1000,
            "kilometers": 1000,
            "cm": 0.01,
            "centimeter": 0.01,
            "centimeters": 0.01,
            "mm": 0.001,
            "millimeter": 0.001,
            "millimeters": 0.001,
            "ft": 0.3048,
            "foot": 0.3048,
            "feet": 0.3048,
            "in": 0.0254,
            "inch": 0.0254,
            "inches": 0.0254,
            "yd": 0.9144,
            "yard": 0.9144,
            "yards": 0.9144,
            "mi": 1609.34,
            "mile": 1609.34,
            "miles": 1609.34,
        }

        # Weight conversions (to kg)
        self.weight_units = {
            "kg": 1,
            "kilogram": 1,
            "kilograms": 1,
            "g": 0.001,
            "gram": 0.001,
            "grams": 0.001,
            "lb": 0.453592,
            "pound": 0.453592,
            "pounds": 0.453592,
            "oz": 0.0283495,
            "ounce": 0.0283495,
            "ounces": 0.0283495,
            "stone": 6.35029,
            "stones": 6.35029,
        }

    def parse_command(self, message_content):
        """
        Parse calculator or conversion commands
        """
        content = _prepare_calculator_request(message_content)
        if not content:
            return None
        content_lower = content.casefold()

        conversion_prefix = (
            r"(?:(?:konverter(?:e)?|convert|omgjør|gjør\s+om|gjer\s+om)\s+)?"
        )
        conversion_connector = r"(?:til|to|i|in)"
        number = r"-?\d+(?:[.,]\d+)?"

        def decimal_value(raw_value):
            return float(raw_value.replace(",", "."))

        def unit_alternation(units):
            return "|".join(
                re.escape(unit) for unit in sorted(units, key=len, reverse=True)
            )

        # Temperature conversion with explicit temperature units.
        temp_units = unit_alternation(self.temp_units)
        temp_pattern = (
            rf"^{conversion_prefix}({number})\s*°?\s*({temp_units})\b"
            rf"(?:\s+{conversion_connector}?\s*°?\s*({temp_units})\b)?$"
        )
        match = re.fullmatch(temp_pattern, content_lower)
        if match:
            return {
                "type": "temperature",
                "value": decimal_value(match.group(1)),
                "from": match.group(2),
                "to": match.group(3) if match.group(3) else None,
            }

        # Length conversion
        length_units = unit_alternation(self.length_units)
        length_pattern = (
            rf"^{conversion_prefix}({number})\s*({length_units})\b"
            rf"\s+{conversion_connector}\s+({length_units})\b$"
        )
        match = re.fullmatch(length_pattern, content_lower)
        if match:
            return {
                "type": "length",
                "value": decimal_value(match.group(1)),
                "from": match.group(2),
                "to": match.group(3),
            }

        # Weight conversion
        weight_units = unit_alternation(self.weight_units)
        weight_pattern = (
            rf"^{conversion_prefix}({number})\s*({weight_units})\b"
            rf"\s+{conversion_connector}\s+({weight_units})\b$"
        )
        match = re.fullmatch(weight_pattern, content_lower)
        if match:
            return {
                "type": "weight",
                "value": decimal_value(match.group(1)),
                "from": match.group(2),
                "to": match.group(3),
            }

        # Currency is intentionally last: both units must be known currencies.
        # An explicit "convert cats to dogs" is not a command.
        currency_units = unit_alternation(self.exchange_rates)
        currency_pattern = (
            rf"^{conversion_prefix}({number})\s*({currency_units})\b"
            rf"\s+{conversion_connector}\s+({currency_units})\b$"
        )
        match = re.fullmatch(currency_pattern, content_lower)
        if match:
            return {
                "type": "currency",
                "amount": decimal_value(match.group(1)),
                "from": match.group(2),
                "to": match.group(3),
            }

        # Math calculation
        # Pattern: "regn ut 2+2", "calculate 150 * 1.25"
        calc_patterns = [
            re.compile(
                r"^(?:regn(?:e)?\s+ut|rekn(?:e)?\s+ut|kalkuler(?:e)?|"
                r"kalk|calculate|calc|compute|work\s+out)\s+"
                r"(?P<expression>.+)$",
                re.IGNORECASE,
            ),
            re.compile(
                r"^(?:hva|kva|ka)\s+er\s+(?P<expression>.+)$|"
                r"^what\s+is\s+(?P<expression_en>.+)$",
                re.IGNORECASE,
            ),
        ]
        for index, pattern in enumerate(calc_patterns):
            match = pattern.fullmatch(content)
            if match:
                expression = (
                    match.groupdict().get("expression")
                    or match.groupdict().get("expression_en")
                    or ""
                ).strip()
                expression = expression.rstrip("?!.").strip()
                valid_expression = (
                    expression
                    and re.fullmatch(_MATH_EXPRESSION, expression)
                    and re.search(r"\d", expression)
                )
                question_has_operator = (
                    (
                        index == 0
                        or _QUESTION_MATH_OPERATOR.search(expression) is not None
                    )
                    and _DATE_LIKE_EXPRESSION.search(expression) is None
                )
                if valid_expression and question_has_operator:
                    return {"type": "math", "expression": expression}

        return None

    def calculate(self, cmd, lang="no"):
        """Perform calculation"""
        if not cmd:
            return None

        calc_type = cmd["type"]

        if calc_type == "currency":
            return self._convert_currency(cmd, lang)
        elif calc_type == "temperature":
            return self._convert_temperature(cmd, lang)
        elif calc_type == "length":
            return self._convert_length(cmd, lang)
        elif calc_type == "weight":
            return self._convert_weight(cmd, lang)
        elif calc_type == "math":
            return self._do_math(cmd, lang)

        return None

    def _convert_currency(self, cmd, lang):
        """Convert currency"""
        amount = cmd["amount"]
        from_curr = cmd["from"].lower()
        to_curr = cmd["to"].lower()

        # Get exchange rate
        rate = 1.0
        if from_curr == to_curr:
            rate = 1.0
        elif (
            from_curr in self.exchange_rates
            and to_curr in self.exchange_rates[from_curr]
        ):
            rate = self.exchange_rates[from_curr][to_curr]
        elif (
            to_curr in self.exchange_rates and from_curr in self.exchange_rates[to_curr]
        ):
            rate = 1 / self.exchange_rates[to_curr][from_curr]
        else:
            if lang == "no":
                return f"💱 Ukjent valutakonvertering: {from_curr.upper()} → {to_curr.upper()}"
            else:
                return (
                    f"💱 Unknown currency pair: {from_curr.upper()} → {to_curr.upper()}"
                )

        result = amount * rate

        currency_symbols = {
            "usd": "$",
            "nok": "kr",
            "eur": "€",
            "gbp": "£",
            "btc": "₿",
            "eth": "Ξ",
        }

        from_sym = currency_symbols.get(from_curr, from_curr.upper())
        to_sym = currency_symbols.get(to_curr, to_curr.upper())

        if lang == "no":
            return f"💱 **Valutakonvertering**\n{from_sym}{amount:,.2f} = {to_sym}{result:,.2f}"
        else:
            return f"💱 **Currency Conversion**\n{from_sym}{amount:,.2f} = {to_sym}{result:,.2f}"

    def _convert_temperature(self, cmd, lang):
        """Convert temperature"""
        value = cmd["value"]
        from_unit = cmd["from"].lower()
        to_unit = cmd["to"].lower() if cmd["to"] else None

        # Auto-detect target if not specified
        if not to_unit:
            if "c" in from_unit:
                to_unit = "f"
            elif "f" in from_unit:
                to_unit = "c"
            else:
                to_unit = "c"

        # Convert to Celsius first
        if "c" in from_unit:
            celsius = value
        elif "f" in from_unit:
            celsius = (value - 32) * 5 / 9
        elif "k" in from_unit:
            celsius = value - 273.15
        else:
            celsius = value

        # Convert from Celsius to target
        if "c" in to_unit:
            result = celsius
            unit = "°C"
        elif "f" in to_unit:
            result = (celsius * 9 / 5) + 32
            unit = "°F"
        elif "k" in to_unit:
            result = celsius + 273.15
            unit = "K"
        else:
            result = celsius
            unit = "°C"

        if lang == "no":
            return f"🌡️ **Temperatur**\n{value}° → {result:.1f}{unit}"
        else:
            return f"🌡️ **Temperature**\n{value}° → {result:.1f}{unit}"

    def _convert_length(self, cmd, lang):
        """Convert length"""
        value = cmd["value"]
        from_unit = cmd["from"].lower()
        to_unit = cmd["to"].lower()

        # Convert to meters then to target
        meters = value * self.length_units.get(from_unit, 1)
        result = meters / self.length_units.get(to_unit, 1)

        if lang == "no":
            return f"📏 **Lengde**\n{value} {from_unit} = {result:.2f} {to_unit}"
        else:
            return f"📏 **Length**\n{value} {from_unit} = {result:.2f} {to_unit}"

    def _convert_weight(self, cmd, lang):
        """Convert weight"""
        value = cmd["value"]
        from_unit = cmd["from"].lower()
        to_unit = cmd["to"].lower()

        # Convert to kg then to target
        kg = value * self.weight_units.get(from_unit, 1)
        result = kg / self.weight_units.get(to_unit, 1)

        if lang == "no":
            return f"⚖️ **Vekt**\n{value} {from_unit} = {result:.2f} {to_unit}"
        else:
            return f"⚖️ **Weight**\n{value} {from_unit} = {result:.2f} {to_unit}"

    def _validate_expression(self, expression: str) -> tuple[bool, str]:
        """
        Validate math expression before evaluation
        
        Args:
            expression: The math expression to validate
            
        Returns:
            (is_valid, error_message)
        """
        # Length check
        if len(expression) > 100:
            return False, "Expression too long (max 100 chars)"
        
        # Parentheses depth check
        depth = 0
        max_depth = 0
        for char in expression:
            if char == '(':
                depth += 1
                max_depth = max(max_depth, depth)
                if depth > 5:
                    return False, "Expression too complex (max 5 nested levels)"
            elif char == ')':
                depth -= 1
                if depth < 0:
                    return False, "Unbalanced parentheses"
        
        if depth != 0:
            return False, "Unbalanced parentheses"
        
        # Operator count check
        operator_count = sum(1 for c in expression if c in '+-*/')
        if operator_count > 20:
            return False, "Too many operators (max 20)"
        
        return True, "Valid"

    def _do_math(self, cmd, lang):
        """Perform math calculation"""
        expression = cmd["expression"]

        # Clean expression
        expression = (
            expression.replace("x", "*")
            .replace("X", "*")
            .replace("×", "*")
            .replace(":", "/")
            .replace(",", ".")
        )

        # Validate expression
        is_valid, error_msg = self._validate_expression(expression)
        if not is_valid:
            if lang == "no":
                return f"❌ {error_msg}"
            else:
                return f"❌ {error_msg}"

        # Only allow safe characters
        if not re.match(r"^[\d\+\-\*\/\(\)\.\s]+$", expression):
            if lang == "no":
                return "❌ Ugyldig uttrykk"
            else:
                return "❌ Invalid expression"

        try:
            result = simple_eval(expression)

            # Format result
            if isinstance(result, float):
                if result == int(result):
                    result = int(result)
                else:
                    result = round(result, 4)

            if lang == "no":
                return f"🧮 **Resultat:** {result}"
            else:
                return f"🧮 **Result:** {result}"
        except (InvalidExpression, Exception) as e:
            print(f"[CALC] Error: {e}")
            if lang == "no":
                return "❌ Kunne ikke regne ut"
            else:
                return "❌ Could not calculate"


def parse_calculator_command(message_content):
    """Convenience function"""
    manager = CalculatorManager()
    return manager.parse_command(message_content)


def calculate(message_content, lang="no"):
    """Quick calculate function"""
    manager = CalculatorManager()
    cmd = manager.parse_command(message_content)
    if cmd:
        return manager.calculate(cmd, lang)
    return None
