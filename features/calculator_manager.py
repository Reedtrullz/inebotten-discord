#!/usr/bin/env python3
"""
Calculator & Unit Converter Manager for Inebotten
Performs calculations and unit conversions
"""

import re
from simpleeval import simple_eval, InvalidExpression


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
        content_lower = message_content.lower()

        # Remove @inebotten
        content = message_content.replace("@inebotten", "").strip()
        content_lower = content_lower.replace("@inebotten", "").strip()

        # Currency conversion
        # Pattern: "100 USD til NOK", "convert 50 EUR to USD"
        currency_pattern = (
            r"(?:(?:konverter|convert)\s+)?(\d+(?:\.\d+)?)\s*(\w+)\s+(?:til|to)\s+(\w+)"
        )
        match = re.search(currency_pattern, content_lower)
        if match:
            return {
                "type": "currency",
                "amount": float(match.group(1)),
                "from": match.group(2),
                "to": match.group(3),
            }

        # Temperature conversion
        # Pattern: "25C til F", "convert 100 fahrenheit to celsius"
        temp_pattern = r"(?:(?:konverter|convert)\s+)?(-?\d+(?:\.\d+)?)\s*(c|celsius|f|fahrenheit|k|kelvin)\s+(?:til|to)?\s*(c|celsius|f|fahrenheit|k|kelvin)?"
        match = re.search(temp_pattern, content_lower)
        if match:
            return {
                "type": "temperature",
                "value": float(match.group(1)),
                "from": match.group(2),
                "to": match.group(3) if match.group(3) else None,
            }

        # Length conversion
        length_pattern = r"(?:(?:konverter|convert)\s+)?(\d+(?:\.\d+)?)\s*(m|km|cm|mm|ft|foot|feet|in|inch|inches|yd|yard|yards|mi|mile|miles)\s+(?:til|to)\s+(m|km|cm|mm|ft|foot|feet|in|inch|inches|yd|yard|yards|mi|mile|miles)"
        match = re.search(length_pattern, content_lower)
        if match:
            return {
                "type": "length",
                "value": float(match.group(1)),
                "from": match.group(2),
                "to": match.group(3),
            }

        # Weight conversion
        weight_pattern = r"(?:(?:konverter|convert)\s+)?(\d+(?:\.\d+)?)\s*(kg|kilogram|g|gram|lb|pound|pounds|oz|ounce|ounces|stone|stones)\s+(?:til|to)\s+(kg|kilogram|g|gram|lb|pound|pounds|oz|ounce|ounces|stone|stones)"
        match = re.search(weight_pattern, content_lower)
        if match:
            return {
                "type": "weight",
                "value": float(match.group(1)),
                "from": match.group(2),
                "to": match.group(3),
            }

        # Math calculation
        # Pattern: "regn ut 2+2", "calculate 150 * 1.25"
        calc_patterns = [
            r"(?:regn ut|calculate|calc|compute)\s+(.+)",
            r"(?:hva er|what is)\s+(\d+\s*[-+*/]\s*\d+)",
        ]
        for pattern in calc_patterns:
            match = re.search(pattern, content_lower)
            if match:
                return {"type": "math", "expression": match.group(1)}

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
        if (
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
        expression = expression.replace("x", "*").replace(":", "/")

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
