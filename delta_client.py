"""
=============================================================================
 DELTA_CLIENT.PY — Delta Exchange Authenticated API Client
=============================================================================
 Handles:
   • HMAC-SHA256 request signing
   • Account balance fetching
   • Order placement (market orders)
   • Order cancellation
   • Position queries
   • Leverage setting
 
 Supports both LIVE and PAPER modes.
=============================================================================
"""

import time
import json
import hashlib
import hmac
import requests
from datetime import datetime, timezone, timedelta

import config

IST = timezone(timedelta(hours=5, minutes=30))


class DeltaClient:
    """Authenticated Delta Exchange India API client."""

    def __init__(self):
        self.base_url = config.DELTA_BASE_URL
        self.api_key = config.DELTA_API_KEY
        self.api_secret = config.DELTA_API_SECRET
        self.product_id = config.DELTA_PRODUCT_ID
        self.symbol = config.DELTA_SYMBOL
        self.is_paper = config.TRADING_MODE == "paper"

        if not self.is_paper and (not self.api_key or not self.api_secret
                                   or "your_" in self.api_key):
            raise ValueError(
                "DELTA_API_KEY and DELTA_API_SECRET required for live trading. "
                "Set TRADING_MODE=paper for simulation."
            )

    # ─── Auth Helpers ───────────────────────────────────────────────────

    def _get_signature(self, method, path, query_string="", body=""):
        """Generate HMAC-SHA256 signature for Delta Exchange API."""
        timestamp = str(int(time.time()))
        message = method + timestamp + path
        if query_string:
            message += "?" + query_string
        if body:
            message += body

        signature = hmac.new(
            self.api_secret.encode("utf-8"),
            message.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

        return signature, timestamp

    def _auth_headers(self, method, path, query_string="", body=""):
        """Build authenticated headers."""
        signature, timestamp = self._get_signature(method, path, query_string, body)
        return {
            "api-key": self.api_key,
            "signature": signature,
            "timestamp": timestamp,
            "Content-Type": "application/json",
        }

    def _request(self, method, path, params=None, body=None, auth=True):
        """Make an authenticated or public API request."""
        url = self.base_url + path
        query_string = ""
        body_str = ""

        if params:
            query_string = "&".join(f"{k}={v}" for k, v in sorted(params.items()))
        if body:
            body_str = json.dumps(body)

        headers = {"Content-Type": "application/json"}
        if auth:
            headers = self._auth_headers(method, path, query_string, body_str)

        try:
            if method == "GET":
                resp = requests.get(url, params=params, headers=headers, timeout=15)
            elif method == "POST":
                resp = requests.post(url, data=body_str, headers=headers, timeout=15)
            elif method == "PUT":
                resp = requests.put(url, data=body_str, headers=headers, timeout=15)
            elif method == "DELETE":
                resp = requests.delete(url, params=params, headers=headers, timeout=15)
            else:
                return None

            if resp.status_code == 200:
                data = resp.json()
                if data.get("success"):
                    return data.get("result")
                else:
                    error = data.get("error", {})
                    print(f"  [DELTA] API error: {error}")
                    return None
            else:
                print(f"  [DELTA] HTTP {resp.status_code}: {resp.text[:300]}")
                return None

        except requests.exceptions.Timeout:
            print(f"  [DELTA] Request timed out: {method} {path}")
            return None
        except Exception as e:
            print(f"  [DELTA] Request error: {e}")
            return None

    # ─── Public Endpoints ───────────────────────────────────────────────

    def get_ticker(self):
        """Fetch current ticker (public, no auth)."""
        url = f"{self.base_url}/v2/tickers/{self.symbol}"
        try:
            resp = requests.get(url, timeout=10)
            data = resp.json()
            if data.get("success"):
                r = data["result"]
                return {
                    "mark_price": float(r.get("mark_price", 0)),
                    "close": float(r.get("close", 0)),
                    "high": float(r.get("high", 0)),
                    "low": float(r.get("low", 0)),
                    "open": float(r.get("open", 0)),
                    "volume": float(r.get("volume", 0)),
                    "turnover": float(r.get("turnover", 0)),
                    "open_interest": float(r.get("oi", 0)),
                    "funding_rate": float(r.get("funding_rate", 0) or 0),
                    "product_id": r.get("product_id", self.product_id),
                    "symbol": r.get("symbol", self.symbol),
                    "spot_price": float(r.get("spot_price", 0) or 0),
                }
        except Exception as e:
            print(f"  [DELTA] Ticker error: {e}")
        return None

    def get_orderbook(self, depth=20):
        """Fetch L2 orderbook (public)."""
        url = f"{self.base_url}/v2/l2orderbook/{self.symbol}"
        try:
            resp = requests.get(url, timeout=10)
            data = resp.json()
            if data.get("success"):
                r = data["result"]
                return {
                    "buy": r.get("buy", [])[:depth],
                    "sell": r.get("sell", [])[:depth],
                }
        except Exception as e:
            print(f"  [DELTA] Orderbook error: {e}")
        return None

    def get_recent_trades(self):
        """Fetch recent trades (public)."""
        url = f"{self.base_url}/v2/trades/{self.symbol}"
        try:
            resp = requests.get(url, timeout=10)
            data = resp.json()
            if data.get("success"):
                return data.get("result", [])
        except Exception as e:
            print(f"  [DELTA] Trades error: {e}")
        return None

    # ─── Authenticated Endpoints ────────────────────────────────────────

    def get_wallet_balances(self):
        """Fetch all wallet balances. Works in both paper and live mode if keys are set."""
        # Even in paper mode, fetch real balance if API keys available
        if not self.api_key or not self.api_secret or "your_" in self.api_key:
            return self._paper_balances()

        result = self._request("GET", "/v2/wallet/balances")
        if result is None:
            if self.is_paper:
                return self._paper_balances()
            return None

        balances = {}
        for b in result:
            asset = b.get("asset_symbol", "")
            balances[asset] = {
                "balance": float(b.get("balance", 0)),
                "available_balance": float(b.get("available_balance", 0)),
                "order_margin": float(b.get("order_margin", 0)),
                "position_margin": float(b.get("position_margin", 0)),
                "unrealized_pnl": float(b.get("unrealised_pnl", 0)),
            }
        return balances

    def get_btc_balance(self):
        """Get BTC wallet balance (used for inverse perpetuals)."""
        balances = self.get_wallet_balances()
        if balances is None:
            return None

        # For inverse perpetuals, margin is in BTC
        btc = balances.get("BTC", {})
        return {
            "total_btc": btc.get("balance", 0),
            "available_btc": btc.get("available_balance", 0),
            "position_margin_btc": btc.get("position_margin", 0),
            "unrealized_pnl_btc": btc.get("unrealized_pnl", 0),
        }

    def get_available_balance_usd(self, btc_price):
        """
        Get available balance in USD terms.
        
        Delta Exchange India keeps balances in INR internally but the wallet API 
        returns balances denominated in the settling asset. For BTCUSD (USD-settled),
        the balance is in USD. For INR deposits, Delta converts at a fixed rate.
        
        We check multiple asset symbols: USD, INR, USDT, BTC.
        """
        balances = self.get_wallet_balances()
        if balances is None:
            if self.is_paper:
                return self._paper_balance_usd()
            return None

        # Delta India: balances could be under USD, INR, USDT, or BTC
        available_usd = 0
        total_usd = 0

        # Check USD balance first (most common for BTCUSD margining)
        for asset in ["USD", "USDT", "INR"]:
            b = balances.get(asset, {})
            avail = b.get("available_balance", 0)
            total = b.get("balance", 0)
            if avail > 0:
                if asset == "INR":
                    # Convert INR to USD (approximate, Delta uses ~85 fixed rate)
                    available_usd += avail / 85.0
                    total_usd += total / 85.0
                else:
                    available_usd += avail
                    total_usd += total

        # Also check BTC balance (for inverse perps)
        btc_b = balances.get("BTC", {})
        if btc_b.get("available_balance", 0) > 0 and btc_price > 0:
            available_usd += btc_b["available_balance"] * btc_price
            total_usd += btc_b.get("balance", 0) * btc_price

        if available_usd == 0 and self.is_paper:
            return self._paper_balance_usd()

        return {
            "available_usd": round(available_usd, 2),
            "total_usd": round(total_usd, 2),
            "available_btc": round(available_usd / btc_price, 8) if btc_price > 0 else 0,
            "total_btc": round(total_usd / btc_price, 8) if btc_price > 0 else 0,
            "btc_price": btc_price,
            "raw_balances": {k: v for k, v in balances.items() if v.get("balance", 0) > 0},
        }

    def get_open_positions(self):
        """Fetch all open positions."""
        if self.is_paper:
            return []

        result = self._request("GET", "/v2/positions")
        if result is None:
            return []
        return result

    def get_position_for_product(self):
        """Get position for our BTCUSD product specifically."""
        positions = self.get_open_positions()
        for p in positions:
            if p.get("product_id") == self.product_id:
                size = int(p.get("size", 0))
                if size != 0:
                    return {
                        "size": size,
                        "direction": "LONG" if size > 0 else "SHORT",
                        "entry_price": float(p.get("entry_price", 0)),
                        "margin": float(p.get("margin", 0)),
                        "liquidation_price": float(p.get("liquidation_price", 0)),
                        "unrealized_pnl": float(p.get("unrealised_pnl", 0)),
                        "product_id": self.product_id,
                    }
        return None

    def set_leverage(self, leverage=None):
        """Set leverage for our product."""
        if self.is_paper:
            return True

        lev = leverage or config.LEVERAGE
        body = {
            "product_id": self.product_id,
            "leverage": str(lev),
        }
        result = self._request("POST", "/v2/orders/leverage", body=body)
        if result is not None:
            print(f"  [DELTA] Leverage set to {lev}x")
            return True
        return False

    def place_market_order(self, side, size, reduce_only=False):
        """
        Place a market order on Delta Exchange.
        
        side: "buy" or "sell"
        size: number of contracts (1 contract = $1 USD for inverse perps)
        reduce_only: True for closing positions
        """
        if self.is_paper:
            return self._paper_order(side, size, reduce_only)

        body = {
            "product_id": self.product_id,
            "size": int(size),
            "side": side.lower(),
            "order_type": "market_order",
        }
        if reduce_only:
            body["reduce_only"] = True

        print(f"  [DELTA] Placing {side.upper()} market order: {size} contracts"
              f"{' (reduce_only)' if reduce_only else ''}")

        result = self._request("POST", "/v2/orders", body=body)
        if result is not None:
            order_id = result.get("id", "unknown")
            avg_fill = float(result.get("average_fill_price", 0))
            print(f"  [DELTA] Order filled: ID={order_id} AvgPrice=${avg_fill:,.2f}")
            return {
                "order_id": order_id,
                "side": side,
                "size": size,
                "avg_fill_price": avg_fill,
                "status": result.get("state", "unknown"),
                "timestamp": int(time.time()),
            }

        print(f"  [DELTA] Order FAILED: {side} {size} contracts")
        return None

    def place_bracket_order(self, side, size, stop_loss_price, take_profit_price):
        """
        Place market order with bracket (SL + TP) on Delta Exchange.
        Uses stop_order for SL and take_profit_order for TP.
        """
        # First place the market entry order
        entry_result = self.place_market_order(side, size)
        if entry_result is None:
            return None

        entry_price = entry_result["avg_fill_price"]

        # Place stop-loss order
        sl_side = "sell" if side.lower() == "buy" else "buy"
        sl_result = self._place_stop_order(
            sl_side, size, stop_loss_price, reduce_only=True,
            order_type="stop_loss"
        )

        # Place take-profit order
        tp_result = self._place_stop_order(
            sl_side, size, take_profit_price, reduce_only=True,
            order_type="take_profit"
        )

        return {
            "entry": entry_result,
            "entry_price": entry_price,
            "stop_loss_order": sl_result,
            "take_profit_order": tp_result,
        }

    def _place_stop_order(self, side, size, trigger_price, reduce_only=True,
                          order_type="stop_loss"):
        """Place a stop/TP order."""
        if self.is_paper:
            return {"paper": True, "trigger_price": trigger_price, "type": order_type}

        # Delta Exchange stop order format
        body = {
            "product_id": self.product_id,
            "size": int(size),
            "side": side.lower(),
            "order_type": "market_order",
            "stop_order_type": "stop_loss_order",
            "stop_price": str(round(trigger_price, 1)),
        }
        if reduce_only:
            body["reduce_only"] = True

        # For take profit, use different stop type
        if order_type == "take_profit":
            body["stop_order_type"] = "take_profit_order"
            body["stop_price"] = str(round(trigger_price, 1))

        result = self._request("POST", "/v2/orders", body=body)
        if result:
            return {
                "order_id": result.get("id", "unknown"),
                "trigger_price": trigger_price,
                "type": order_type,
            }
        return None

    def cancel_all_orders(self):
        """Cancel all open orders for our product."""
        if self.is_paper:
            return True

        body = {"product_id": self.product_id, "cancel_limit_orders": True,
                "cancel_stop_orders": True}
        result = self._request("DELETE", "/v2/orders/all", body=body)
        return result is not None

    def close_position(self, size=None):
        """
        Close the current position.
        If size is None, fetches position and closes entire thing.
        """
        if self.is_paper:
            return self._paper_close()

        pos = self.get_position_for_product()
        if pos is None:
            print("  [DELTA] No position to close")
            return None

        close_size = abs(size or pos["size"])
        close_side = "sell" if pos["direction"] == "LONG" else "buy"

        # Cancel existing SL/TP orders first
        self.cancel_all_orders()

        return self.place_market_order(close_side, close_size, reduce_only=True)

    # ─── Paper Trading Stubs ────────────────────────────────────────────

    def _paper_balances(self):
        """Simulated balances for paper mode."""
        return {
            "BTC": {
                "balance": 0.01,
                "available_balance": 0.01,
                "order_margin": 0,
                "position_margin": 0,
                "unrealized_pnl": 0,
            }
        }

    def _paper_balance_usd(self):
        """Paper mode USD balance."""
        return {
            "available_btc": 0.01,
            "available_usd": 870.0,  # approximate
            "total_btc": 0.01,
            "total_usd": 870.0,
            "btc_price": 87000,
        }

    def _paper_order(self, side, size, reduce_only):
        """Simulated order for paper mode."""
        ticker = self.get_ticker()
        price = ticker["mark_price"] if ticker else 87000
        print(f"  [PAPER] {side.upper()} {size} contracts @ ~${price:,.2f}"
              f"{' (reduce_only)' if reduce_only else ''}")
        return {
            "order_id": f"paper_{int(time.time())}",
            "side": side,
            "size": size,
            "avg_fill_price": price,
            "status": "filled",
            "timestamp": int(time.time()),
            "paper": True,
        }

    def _paper_close(self):
        """Simulated close for paper mode."""
        ticker = self.get_ticker()
        price = ticker["mark_price"] if ticker else 87000
        print(f"  [PAPER] Position closed @ ~${price:,.2f}")
        return {
            "order_id": f"paper_close_{int(time.time())}",
            "avg_fill_price": price,
            "status": "filled",
            "paper": True,
        }
