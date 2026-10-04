#!/usr/bin/env python3
"""
Calculator & Unit Converter Manager for Inebotten
Performs calculations and unit conversions
"""

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import Literal

from simpleeval import simple_eval, InvalidExpression


@dataclass(frozen=True)
class RateSnapshot:
    """A coherent set of currency rates expressed per one unit of ``base``."""

    source: str
    effective_at: datetime | None
    base: str
    rates: dict[str, Decimal]
    status: Literal["fresh", "stale", "demonstration"]

    def __post_init__(self):
        if self.status not in {"fresh", "stale", "demonstration"}:
            raise ValueError("status must be fresh, stale, or demonstration")
        if self.effective_at is not None and (
            self.effective_at.tzinfo is None or self.effective_at.utcoffset() is None
        ):
            raise ValueError("effective_at must be timezone-aware")
        normalized = {code.upper(): Decimal(rate) for code, rate in self.rates.items()}
        base = self.base.upper()
        if base not in normalized or normalized[base] != Decimal("1"):
            raise ValueError("base rate must be present and equal to 1")
        if any(rate <= 0 for rate in normalized.values()):
            raise ValueError("rates must be positive")
        if self.status == "fresh" and self.effective_at is None:
            raise ValueError("fresh snapshots require an effective time")
        object.__setattr__(self, "base", base)
        object.__setattr__(self, "rates", normalized)


def convert_currency(
    amount: Decimal, source: str, target: str, snapshot: RateSnapshot
) -> Decimal:
    """Convert using one base-rate snapshot with explicit currency precision."""
    source = source.upper()
    target = target.upper()
    if source not in snapshot.rates or target not in snapshot.rates:
        raise ValueError(f"Unsupported currency pair: {source} -> {target}")
    converted = Decimal(amount) * snapshot.rates[target] / snapshot.rates[source]
    places = 8 if target == "BTC" else 2
    quantum = Decimal(1).scaleb(-places)
    return converted.quantize(quantum, rounding=ROUND_HALF_UP)


DEMONSTRATION_RATES = RateSnapshot(
    source="fixed demonstration values",
    effective_at=None,
    base="USD",
    rates={
        "USD": Decimal("1"),
        "NOK": Decimal("10.85"),
        "EUR": Decimal("0.92"),
        "GBP": Decimal("0.79"),
        "BTC": Decimal("1") / Decimal("67420"),
    },
    status="demonstration",
)


class CalculatorManager:
    """
    Handles calculations and unit conversions
    """

    def __init__(self):
        self.rate_snapshot = DEMONSTRATION_RATES

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
        # Require "konverter" OR recognized currency units to avoid "10 venner til middag"
        currency_pattern = (
            r"(?:(?:konverter|convert|omgjør)\s+)?(\d+(?:\.\d+)?)\s*(\w+)\s+(?:til|to)\s+(\w+)"
        )
        match = re.search(currency_pattern, content_lower)
        if match:
            amount = float(match.group(1))
            from_unit = match.group(2)
            to_unit = match.group(3)
            
            is_recognized = (
                from_unit.upper() in self.rate_snapshot.rates
                or to_unit.upper() in self.rate_snapshot.rates
            )
            is_explicit = any(re.search(rf"\b{re.escape(w)}\b", content_lower) for w in ["konverter", "convert", "omgjør"])
            
            if is_recognized or is_explicit:
                return {
                    "type": "currency",
                    "amount": amount,
                    "from": from_unit,
                    "to": to_unit,
                    "requires_current": bool(
                        re.search(
                            r"\b(?:now|current|currently|today|live|nå|nåværende|fersk|dagens|i dag|oppdatert)\b",
                            content_lower,
                        )
                    ),
                }

        # Temperature conversion with explicit temperature units.
        temp_pattern = r"(?:(?:konverter|convert|omgjør)\s+)?(-?\d+(?:\.\d+)?)\s*(c|celsius|f|fahrenheit|k|kelvin)\b(?:\s+(?:til|to)?\s*(c|celsius|f|fahrenheit|k|kelvin)\b)?"
        match = re.search(temp_pattern, content_lower)
        if match:
            return {
                "type": "temperature",
                "value": float(match.group(1)),
                "from": match.group(2),
                "to": match.group(3) if match.group(3) else None,
            }

        # Length conversion
        length_pattern = r"(?:(?:konverter|convert)\s+)?(\d+(?:\.\d+)?)\s*(m|km|cm|mm|ft|foot|feet|in|inch|inches|yd|yard|yards|mi|mile|miles)\b\s+(?:til|to)\s+(m|km|cm|mm|ft|foot|feet|in|inch|inches|yd|yard|yards|mi|mile|miles)\b"
        match = re.search(length_pattern, content_lower)
        if match:
            return {
                "type": "length",
                "value": float(match.group(1)),
                "from": match.group(2),
                "to": match.group(3),
            }

        # Weight conversion
        weight_pattern = r"(?:(?:konverter|convert)\s+)?(\d+(?:\.\d+)?)\s*(kg|kilogram|g|gram|lb|pound|pounds|oz|ounce|ounces|stone|stones)\b\s+(?:til|to)\s+(kg|kilogram|g|gram|lb|pound|pounds|oz|ounce|ounces|stone|stones)\b"
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
        amount = Decimal(str(cmd["amount"]))
        from_curr = cmd["from"].lower()
        to_curr = cmd["to"].lower()
        snapshot = self.rate_snapshot
        if cmd.get("requires_current") and snapshot.status != "fresh":
            return (
                "❌ Ingen fersk valutakurs er tilgjengelig."
                if lang == "no"
                else "❌ No fresh exchange rate is available."
            )
        try:
            result = convert_currency(amount, from_curr, to_curr, snapshot)
        except ValueError:
            if lang == "no":
                return f"💱 Ukjent valutakonvertering: {from_curr.upper()} → {to_curr.upper()}"
            return f"💱 Unknown currency pair: {from_curr.upper()} → {to_curr.upper()}"

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

        amount_places = 8 if from_curr == "btc" else 2
        result_places = 8 if to_curr == "btc" else 2
        amount_text = f"{amount:,.{amount_places}f}"
        result_text = f"{result:,.{result_places}f}"
        if snapshot.status == "demonstration":
            provenance = (
                "Estimat: demonstrasjonskurs · kilde: faste eksempelverdier · gyldig tidspunkt: ukjent"
                if lang == "no"
                else "Estimated demonstration rate · source: fixed example values · effective time: unknown"
            )
        else:
            effective = (
                snapshot.effective_at.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
                if snapshot.effective_at
                else ("ukjent" if lang == "no" else "unknown")
            )
            freshness = "fresh" if snapshot.status == "fresh" else "stale"
            provenance = (
                f"{freshness.capitalize()} rate · source: {snapshot.source} · effective: {effective}"
            )
            if lang == "no":
                freshness = "fersk" if snapshot.status == "fresh" else "foreldet"
                provenance = f"{freshness.capitalize()} kurs · kilde: {snapshot.source} · gyldig tidspunkt: {effective}"
        rounding = (
            "Avrunding: fiat 2 desimaler, BTC 8"
            if lang == "no"
            else "Rounding: fiat 2 decimal places, BTC 8"
        )
        if lang == "no":
            return f"💱 **Valutakonvertering**\n{from_sym}{amount_text} → {to_sym}{result_text}\n{provenance}\n{rounding}"
        return f"💱 **Currency Conversion**\n{from_sym}{amount_text} → {to_sym}{result_text}\n{provenance}\n{rounding}"

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
