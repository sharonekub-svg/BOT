"""Broker abstraction.

PaperBroker simulates fills against current quotes (default).
PolymarketBroker (execution/polymarket_broker.py) routes real orders.
"""

import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class OrderRequest:
    market_id: str
    token_id: str | None
    outcome: str          # YES | NO
    side: str             # buy | sell
    order_type: str       # market | limit
    qty: float            # shares
    limit_price: float | None = None
    current_bid: float | None = None  # quotes for paper fills
    current_ask: float | None = None


@dataclass
class OrderResult:
    accepted: bool
    order_id: str
    status: str                 # filled | open | rejected
    fill_price: float | None = None
    filled_qty: float = 0.0
    message: str = ""


class Broker(ABC):
    @abstractmethod
    async def place_order(self, request: OrderRequest) -> OrderResult: ...

    @abstractmethod
    async def cancel_order(self, order_id: str) -> bool: ...


class PaperBroker(Broker):
    """Instant simulated fills at the touch; limit orders rest until crossed."""

    def __init__(self, slippage: float = 0.002) -> None:
        self.slippage = slippage
        self.resting: dict[str, OrderRequest] = {}

    async def place_order(self, request: OrderRequest) -> OrderResult:
        order_id = f"paper-{uuid.uuid4().hex[:12]}"

        if request.order_type == "market":
            price = request.current_ask if request.side == "buy" else request.current_bid
            if price is None:
                return OrderResult(False, order_id, "rejected", message="no quote available")
            fill = min(max(price + self.slippage, 0.001), 0.999) if request.side == "buy" else max(
                min(price - self.slippage, 0.999), 0.001
            )
            return OrderResult(True, order_id, "filled", fill_price=round(fill, 4), filled_qty=request.qty)

        # limit order
        if request.limit_price is None:
            return OrderResult(False, order_id, "rejected", message="limit order needs a price")
        crossed = (
            request.side == "buy"
            and request.current_ask is not None
            and request.current_ask <= request.limit_price
        ) or (
            request.side == "sell"
            and request.current_bid is not None
            and request.current_bid >= request.limit_price
        )
        if crossed:
            return OrderResult(
                True, order_id, "filled", fill_price=request.limit_price, filled_qty=request.qty
            )
        self.resting[order_id] = request
        return OrderResult(True, order_id, "open", message="resting limit order")

    async def check_resting(self, order_id: str, bid: float | None, ask: float | None) -> OrderResult | None:
        """Called by the execution loop each scan to try filling resting orders."""
        request = self.resting.get(order_id)
        if request is None:
            return None
        crossed = (request.side == "buy" and ask is not None and ask <= request.limit_price) or (
            request.side == "sell" and bid is not None and bid >= request.limit_price
        )
        if not crossed:
            return None
        del self.resting[order_id]
        return OrderResult(True, order_id, "filled", fill_price=request.limit_price, filled_qty=request.qty)

    async def cancel_order(self, order_id: str) -> bool:
        return self.resting.pop(order_id, None) is not None
