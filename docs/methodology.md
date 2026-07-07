# Methodology

This dashboard uses **public CFTC positioning data** as a weekly market-structure lens.

The CFTC states that Commitments of Traders reports are generally published each **Friday at 3:30 p.m. Eastern Time**, using data from the **preceding Tuesday**. The dashboard should therefore clearly label each update as a Tuesday positioning snapshot released on Friday. [Source](https://www.cftc.gov/MarketReports/CommitmentsofTraders/index.htm)

## Cohort mapping

The dashboard should use proxy language rather than claim direct visibility into CTA books.

### Financial futures / TFF markets

- **Fast money / CTA proxy:** `lev_money_positions_long` minus `lev_money_positions_short`
- **Slow money / allocator proxy:** `asset_mgr_positions_long` minus `asset_mgr_positions_short`
- **Dealer / hedge side:** `dealer_positions_long_all` minus `dealer_positions_short_all`

These fields are available in the CFTC TFF JSON endpoint. [Source](https://publicreporting.cftc.gov/resource/gpe5-46if.json)

### Commodity / Disaggregated markets

- **Fast money proxy:** Managed Money
- **Commercial / hedger side:** Producer / Merchant / Processor / User
- **Secondary institutional side:** Swap Dealers or Other Reportables, depending on the market interpretation

## Core metrics

### Net position

```text
net = long - short
```

Used for every cohort.

### Percentile pressure

Compute each latest net position relative to the market's **entire available history**.
The implementation (`derive_metrics.py`) ranks the latest net against *every* non-missing
weekly observation — an expanding, full-history percentile, **not** a fixed rolling window.

Because history length varies by market (roughly **229 to 1046 weeks**), a given
"90th percentile" is **not directly comparable across markets** — 90th over ~4 years
(e.g. Brent) is a different bar than 90th over ~20 years (e.g. Gold). Always read the
observation count (shown in the tooltip) alongside the percentile. Choosing a uniform
lookback (full-history vs a rolling 3–5yr robust window) is an open convention question
tracked in the analytics audit, not settled here.

### Z-score

```text
z = (current_net - rolling_mean) / rolling_std
```

Use this as a regime/extremes overlay, not as the sole signal.

### 4-week delta

```text
delta_4w = current_net - net_4_weeks_ago
```

This captures recent positioning momentum.

### Price-position dislocation

Compare the sign and magnitude of price changes against positioning changes over the same horizon.

Example interpretations:

- Positioning more bullish, price also rising -> confirmation
- Positioning more bullish, price flat/down -> failed confirmation / vulnerability
- Positioning more bearish, price rising -> squeeze risk

## Watchlist ranking logic

The watchlist should rank **signal importance**, not just position size.

Suggested scoring model:

```text
score =
  0.30 * percentile_extreme
+ 0.20 * zscore_extreme
+ 0.15 * momentum_4w
+ 0.15 * divergence_score
+ 0.10 * oi_confirmation_score
+ 0.10 * price_position_dislocation_score
```

Where:

- `percentile_extreme = abs(percentile - 50) / 50`
- `zscore_extreme = min(abs(zscore), 3) / 3`
- `momentum_4w` is normalized by open interest when possible
- `divergence_score` increases when primary and secondary cohorts move in opposite directions
- `oi_confirmation_score` increases when open interest supports the move
- `price_position_dislocation_score` increases when price and positioning disagree in a meaningful way

## Regime labels

Suggested regime taxonomy:

- **Crowded Long**
- **Crowded Short**
- **Contrarian Long**
- **Contrarian Short**
- **Divergence**
- **Neutral / Transition**

## Narrative discipline

The weekly panel should be generated from rules first.

Good template:

```text
[Market] remains in a [regime] setup. Primary positioning is at the [X]th percentile over the last [lookback] weeks. Over the last 4 weeks, net positioning [rose/fell] by [N] contracts. [Secondary cohort] is [confirming/diverging]. Price is [up/down] [P]% over the same window, implying [confirmation/dislocation].
```

That keeps the dashboard consistent, explainable and publishable.
