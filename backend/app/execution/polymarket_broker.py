"""Live Polymarket broker via py-clob-client.

Optional dependency (`pip install py-clob-client`) and only used when
TRADING_MODE=live with credentials configured. Orders are signed locally with
the configured private key and submitted to the CLOB.
"""

import uuid

from app.config import get_settings
from app.execution.broker import Broker, OrderRequest, OrderResult
from app.logging_config import get_logger

log = get_logger(__name__)

POLYGON_CHAIN_ID = 137


class PolymarketBroker(Broker):
    def __init__(self) -> None:
        self.settings = get_settings()
        self._client = None

    def _build_client(self):
        try:
            from py_clob_client.client import ClobClient as LiveClobClient
            from py_clob_client.clob_types import ApiCreds
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError(
                "Live trading requires py-clob-client: pip install py-clob-client"
            ) from exc

        s = self.settings
        if not s.polymarket_private_key:
            raise RuntimeError("POLYMARKET_PRIVATE_KEY is required for live trading")

        creds = None
        if s.polymarket_api_key:
            creds = ApiCreds(
                api_key=s.polymarket_api_key,
                api_secret=s.polymarket_api_secret,
                api_passphrase=s.polymarket_api_passphrase,
            )
        client = LiveClobClient(
            s.clob_base_url,
            key=s.polymarket_private_key,
            chain_id=POLYGON_CHAIN_ID,
            creds=creds,
            funder=s.polymarket_proxy_address or None,
            signature_type=2 if s.polymarket_proxy_address else 0,
        )
        if creds is None:
            client.set_api_creds(client.create_or_derive_api_creds())
        return client

    @property
    def client(self):
        if self._client is None:
            self._client = self._build_client()
        return self._client

    async def place_order(self, request: OrderRequest) -> OrderResult:
        order_id = f"live-{uuid.uuid4().hex[:12]}"
        if not request.token_id:
            return OrderResult(False, order_id, "rejected", message="missing CLOB token id")
        try:
            from py_clob_client.clob_types import MarketOrderArgs, OrderArgs, OrderType
            from py_clob_client.order_builder.constants import BUY, SELL

            side = BUY if request.side == "buy" else SELL
            if request.order_type == "market":
                args = MarketOrderArgs(
                    token_id=request.token_id,
                    amount=round(request.qty * (request.current_ask or 0.5), 2),
                    side=side,
                )
                signed = self.client.create_market_order(args)
                resp = self.client.post_order(signed, OrderType.FOK)
            else:
                args = OrderArgs(
                    token_id=request.token_id,
                    price=float(request.limit_price),
                    size=float(request.qty),
                    side=side,
                )
                signed = self.client.create_order(args)
                resp = self.client.post_order(signed, OrderType.GTC)

            success = bool(resp.get("success"))
            live_id = resp.get("orderID") or order_id
            status = "filled" if resp.get("status") == "matched" else ("open" if success else "rejected")
            return OrderResult(
                accepted=success,
                order_id=live_id,
                status=status,
                fill_price=request.limit_price if status == "filled" else None,
                filled_qty=request.qty if status == "filled" else 0.0,
                message=str(resp.get("errorMsg") or ""),
            )
        except Exception as exc:
            log.exception("live order failed")
            return OrderResult(False, order_id, "rejected", message=str(exc))

    async def cancel_order(self, order_id: str) -> bool:
        try:
            resp = self.client.cancel(order_id)
            return bool(resp)
        except Exception:
            log.exception("cancel failed for %s", order_id)
            return False
