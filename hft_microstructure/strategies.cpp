// Consolidated HFT strategy sleeves.
// Source-preserving flattening of the original strategy engines; no strategy logic was changed.

#include <algorithm>
#include <array>
#include <cmath>
#include <cstddef>
#include <cstdint>
#include <iostream>
#include <numeric>
#include <vector>

namespace mm {



struct QuoteEvent
{
    std::uint64_t sequence = 0;
    std::uint64_t source_timestamp_ns = 0;
    std::uint64_t parsed_timestamp_ns = 0;
    double bid_price = 0.0;
    double ask_price = 0.0;
    double bid_size = 0.0;
    double ask_size = 0.0;
    std::array<char, 16> symbol{};
};

struct FeatureEvent
{
    std::uint64_t sequence = 0;
    std::uint64_t timestamp_ns = 0;
    double bid_price = 0.0;
    double ask_price = 0.0;
    double bid_size = 0.0;
    double ask_size = 0.0;
    double mid_price = 0.0;
    double spread_bps_100ms = 0.0;
    double spread_bps_1s = 0.0;
    double imbalance_100ms = 0.0;
    double imbalance_1s = 0.0;
    double microprice_edge_100ms_bps = 0.0;
    double microprice_edge_1s_bps = 0.0;
    double quote_rate_1s = 0.0;
    double avg_bid_size_1s = 0.0;
    double avg_ask_size_1s = 0.0;
};

enum class SignalState : int
{
    Neutral = 0,
    LongBias = 1,
    ShortBias = -1
};

struct FeatureBucket
{
    std::uint64_t bucket_id = 0;
    std::uint32_t quote_count = 0;
    double spread_sum_bps = 0.0;
    double imbalance_sum = 0.0;
    double microprice_edge_sum_bps = 0.0;
    double mid_sum = 0.0;
    double bid_size_sum = 0.0;
    double ask_size_sum = 0.0;
};

struct RollingStats
{
    std::uint32_t quote_count = 0;
    double avg_spread_bps = 0.0;
    double avg_imbalance = 0.0;
    double avg_microprice_edge_bps = 0.0;
    double avg_mid = 0.0;
    double avg_bid_size = 0.0;
    double avg_ask_size = 0.0;
};

class FeatureBuilder
{
public:
    static constexpr std::uint64_t bucket_ns = 100000000ULL;
    static constexpr std::size_t bucket_count = 50;

    bool on_quote(const QuoteEvent& quote, FeatureEvent& feature_out)
    {
        if (quote.ask_price <= quote.bid_price || quote.bid_price <= 0.0) {
            return false;
        }

        const std::uint64_t bucket_id = quote.parsed_timestamp_ns / bucket_ns;
        rotate_to(bucket_id);

        FeatureBucket& bucket = buckets_[bucket_id % bucket_count];
        if (bucket.bucket_id != bucket_id) {
            clear_bucket(bucket, bucket_id);
        }

        const double mid = (quote.bid_price + quote.ask_price) * 0.5;
        const double spread_bps = ((quote.ask_price - quote.bid_price) / mid) * 10000.0;
        const double total_size = quote.bid_size + quote.ask_size;
        const double imbalance = total_size > 0.0
            ? (quote.bid_size - quote.ask_size) / total_size
            : 0.0;
        const double microprice =
            ((quote.ask_price * quote.bid_size) + (quote.bid_price * quote.ask_size)) /
            std::max(total_size, 1e-9);
        const double microprice_edge_bps = ((microprice - mid) / mid) * 10000.0;

        ++bucket.quote_count;
        bucket.spread_sum_bps += spread_bps;
        bucket.imbalance_sum += imbalance;
        bucket.microprice_edge_sum_bps += microprice_edge_bps;
        bucket.mid_sum += mid;
        bucket.bid_size_sum += quote.bid_size;
        bucket.ask_size_sum += quote.ask_size;

        const RollingStats short_window = sum_recent(bucket_id, 1);
        const RollingStats long_window = sum_recent(bucket_id, 10);

        feature_out.sequence = quote.sequence;
        feature_out.timestamp_ns = quote.parsed_timestamp_ns;
        feature_out.bid_price = quote.bid_price;
        feature_out.ask_price = quote.ask_price;
        feature_out.bid_size = quote.bid_size;
        feature_out.ask_size = quote.ask_size;
        feature_out.mid_price = mid;
        feature_out.spread_bps_100ms = short_window.avg_spread_bps;
        feature_out.spread_bps_1s = long_window.avg_spread_bps;
        feature_out.imbalance_100ms = short_window.avg_imbalance;
        feature_out.imbalance_1s = long_window.avg_imbalance;
        feature_out.microprice_edge_100ms_bps = short_window.avg_microprice_edge_bps;
        feature_out.microprice_edge_1s_bps = long_window.avg_microprice_edge_bps;
        feature_out.quote_rate_1s = static_cast<double>(long_window.quote_count);
        feature_out.avg_bid_size_1s = long_window.avg_bid_size;
        feature_out.avg_ask_size_1s = long_window.avg_ask_size;
        return true;
    }

private:
    void clear_bucket(FeatureBucket& bucket, std::uint64_t bucket_id)
    {
        bucket.bucket_id = bucket_id;
        bucket.quote_count = 0;
        bucket.spread_sum_bps = 0.0;
        bucket.imbalance_sum = 0.0;
        bucket.microprice_edge_sum_bps = 0.0;
        bucket.mid_sum = 0.0;
        bucket.bid_size_sum = 0.0;
        bucket.ask_size_sum = 0.0;
    }

    void rotate_to(std::uint64_t bucket_id)
    {
        if (last_bucket_id_ == 0) {
            last_bucket_id_ = bucket_id;
            return;
        }

        if (bucket_id <= last_bucket_id_) {
            return;
        }

        const std::uint64_t distance = bucket_id - last_bucket_id_;
        if (distance >= bucket_count) {
            for (FeatureBucket& bucket : buckets_) {
                clear_bucket(bucket, 0);
            }
        } else {
            for (std::uint64_t step = 1; step <= distance; ++step) {
                clear_bucket(buckets_[(last_bucket_id_ + step) % bucket_count], last_bucket_id_ + step);
            }
        }

        last_bucket_id_ = bucket_id;
    }

    RollingStats sum_recent(std::uint64_t ending_bucket_id, std::size_t window_buckets) const
    {
        RollingStats stats;
        for (std::size_t offset = 0; offset < window_buckets; ++offset) {
            const std::uint64_t bucket_id = ending_bucket_id - offset;
            const FeatureBucket& bucket = buckets_[bucket_id % bucket_count];
            if (bucket.bucket_id != bucket_id || bucket.quote_count == 0) {
                continue;
            }

            stats.quote_count += bucket.quote_count;
            stats.avg_spread_bps += bucket.spread_sum_bps;
            stats.avg_imbalance += bucket.imbalance_sum;
            stats.avg_microprice_edge_bps += bucket.microprice_edge_sum_bps;
            stats.avg_mid += bucket.mid_sum;
            stats.avg_bid_size += bucket.bid_size_sum;
            stats.avg_ask_size += bucket.ask_size_sum;
        }

        if (stats.quote_count > 0) {
            const double count = static_cast<double>(stats.quote_count);
            stats.avg_spread_bps /= count;
            stats.avg_imbalance /= count;
            stats.avg_microprice_edge_bps /= count;
            stats.avg_mid /= count;
            stats.avg_bid_size /= count;
            stats.avg_ask_size /= count;
        }

        return stats;
    }

    std::array<FeatureBucket, bucket_count> buckets_{};
    std::uint64_t last_bucket_id_ = 0;
};

struct StrategyOutput
{
    SignalState signal = SignalState::Neutral;
    double score = 0.0;
    double conviction = 0.0;
    double expected_edge_bps = 0.0;
};

struct StrategyConfig
{
    double entry_threshold = 0.30;
    double exit_threshold = 0.08;
    double min_spread_bps = 0.18;
    double max_spread_bps = 2.50;
    double min_quote_rate_1s = 24.0;
    double min_expected_edge_bps = 0.10;
    std::uint64_t max_hold_events = 16;
    double take_profit_bps = 0.45;
    double stop_loss_bps = 0.55;
    double round_trip_cost_bps = 0.06;
    bool enable_longs = true;
    bool enable_shorts = false;
    bool open_only = true;
    std::uint64_t open_window_minutes = 60;
};

struct Position
{
    bool active = false;
    SignalState side = SignalState::Neutral;
    double entry_price = 0.0;
    std::uint64_t entry_sequence = 0;
    std::uint64_t entry_timestamp_ns = 0;
};

struct CompletedTrade
{
    SignalState side = SignalState::Neutral;
    std::uint64_t entry_sequence = 0;
    std::uint64_t exit_sequence = 0;
    std::uint64_t entry_timestamp_ns = 0;
    std::uint64_t exit_timestamp_ns = 0;
    double entry_price = 0.0;
    double exit_price = 0.0;
    double gross_return_bps = 0.0;
    double net_return_bps = 0.0;
    std::uint64_t holding_events = 0;
};

struct StrategyStats
{
    std::uint32_t completed_trades = 0;
    std::uint32_t wins = 0;
    std::uint32_t long_trades = 0;
    std::uint32_t short_trades = 0;
    std::uint32_t long_wins = 0;
    std::uint32_t short_wins = 0;
    double total_net_return_bps = 0.0;
    double average_trade_bps = 0.0;
    double win_rate = 0.0;
    double long_net_return_bps = 0.0;
    double short_net_return_bps = 0.0;
    double long_average_trade_bps = 0.0;
    double short_average_trade_bps = 0.0;
    double long_win_rate = 0.0;
    double short_win_rate = 0.0;
    double max_drawdown_bps = 0.0;
    double sharpe = 0.0;
};

inline double basis_points_return(double entry_price, double exit_price, SignalState side)
{
    if (entry_price <= 0.0 || exit_price <= 0.0 || side == SignalState::Neutral) {
        return 0.0;
    }

    const double raw_return = side == SignalState::LongBias
        ? (exit_price - entry_price) / entry_price
        : (entry_price - exit_price) / entry_price;
    return raw_return * 10000.0;
}

inline double compute_sharpe(const std::vector<double>& returns_bps)
{
    if (returns_bps.size() < 2) {
        return 0.0;
    }

    const double mean =
        std::accumulate(returns_bps.begin(), returns_bps.end(), 0.0) /
        static_cast<double>(returns_bps.size());

    double variance = 0.0;
    for (double value : returns_bps) {
        const double diff = value - mean;
        variance += diff * diff;
    }

    variance /= static_cast<double>(returns_bps.size() - 1);
    const double stddev = std::sqrt(variance);
    if (stddev == 0.0) {
        return 0.0;
    }

    return (mean / stddev) * std::sqrt(static_cast<double>(returns_bps.size()));
}

class MicrostructureStrategy
{
public:
    explicit MicrostructureStrategy(StrategyConfig config = {})
        : config_(config)
    {
    }

    void set_session_start_timestamp_ns(std::uint64_t timestamp_ns)
    {
        if (timestamp_ns != 0) {
            session_start_timestamp_ns_ = timestamp_ns;
        }
    }

    StrategyOutput evaluate_signal(const FeatureEvent& feature) const
    {
        if (!in_open_window(feature.timestamp_ns)) {
            return {};
        }

        const double size_skew =
            (feature.avg_bid_size_1s - feature.avg_ask_size_1s) /
            std::max(feature.avg_bid_size_1s + feature.avg_ask_size_1s, 1e-9);
        const double score =
            (feature.imbalance_100ms * 0.58) +
            (feature.imbalance_1s * 0.18) +
            (feature.microprice_edge_100ms_bps * 0.16) +
            (feature.microprice_edge_1s_bps * 0.05) +
            (size_skew * 0.03);
        const double expected_edge_bps =
            (feature.spread_bps_1s * 0.55) +
            (std::abs(feature.microprice_edge_100ms_bps) * 0.35) +
            (std::abs(feature.microprice_edge_1s_bps) * 0.10);
        const bool spread_ok =
            feature.spread_bps_1s >= config_.min_spread_bps &&
            feature.spread_bps_1s <= config_.max_spread_bps;
        const bool liquidity_ok = feature.quote_rate_1s >= config_.min_quote_rate_1s;
        const bool edge_ok = expected_edge_bps >=
            std::max(config_.min_expected_edge_bps,
                     (feature.spread_bps_1s * 0.35) + config_.round_trip_cost_bps);
        const bool long_alignment =
            feature.imbalance_100ms > 0.0 &&
            feature.microprice_edge_100ms_bps >= 0.0 &&
            feature.microprice_edge_1s_bps >= -0.05;
        const bool short_alignment =
            feature.imbalance_100ms < 0.0 &&
            feature.microprice_edge_100ms_bps <= 0.0 &&
            feature.microprice_edge_1s_bps <= 0.05;

        StrategyOutput output;
        output.score = score;
        output.conviction = std::min(std::abs(score) / 0.25, 1.0);
        output.expected_edge_bps = expected_edge_bps;

        if (config_.enable_longs &&
            spread_ok && liquidity_ok && edge_ok && long_alignment &&
            score > config_.entry_threshold) {
            output.signal = SignalState::LongBias;
        } else if (config_.enable_shorts &&
                   spread_ok && liquidity_ok && edge_ok && short_alignment &&
                   score < -config_.entry_threshold) {
            output.signal = SignalState::ShortBias;
        }

        return output;
    }

    void on_feature(const FeatureEvent& feature)
    {
        if (session_start_timestamp_ns_ == 0) {
            session_start_timestamp_ns_ = feature.timestamp_ns;
        }

        const StrategyOutput output = evaluate_signal(feature);

        if (!position_.active) {
            try_open_position(feature, output);
        } else {
            try_close_position(feature, output);
        }

        last_output_ = output;
    }

    const StrategyOutput& last_output() const
    {
        return last_output_;
    }

    const Position& current_position() const
    {
        return position_;
    }

    const std::vector<CompletedTrade>& completed_trades() const
    {
        return completed_trades_;
    }

    StrategyStats stats() const
    {
        StrategyStats stats;
        if (completed_trades_.empty()) {
            return stats;
        }

        std::vector<double> returns_bps;
        double equity_curve = 0.0;
        double peak = 0.0;
        returns_bps.reserve(completed_trades_.size());

        for (const CompletedTrade& trade : completed_trades_) {
            ++stats.completed_trades;
            stats.total_net_return_bps += trade.net_return_bps;
            if (trade.net_return_bps > 0.0) {
                ++stats.wins;
            }
            if (trade.side == SignalState::LongBias) {
                ++stats.long_trades;
                stats.long_net_return_bps += trade.net_return_bps;
                if (trade.net_return_bps > 0.0) {
                    ++stats.long_wins;
                }
            } else if (trade.side == SignalState::ShortBias) {
                ++stats.short_trades;
                stats.short_net_return_bps += trade.net_return_bps;
                if (trade.net_return_bps > 0.0) {
                    ++stats.short_wins;
                }
            }

            equity_curve += trade.net_return_bps;
            peak = std::max(peak, equity_curve);
            stats.max_drawdown_bps = std::max(stats.max_drawdown_bps, peak - equity_curve);
            returns_bps.push_back(trade.net_return_bps);
        }

        stats.average_trade_bps =
            stats.total_net_return_bps / static_cast<double>(completed_trades_.size());
        stats.win_rate =
            static_cast<double>(stats.wins) / static_cast<double>(completed_trades_.size());
        if (stats.long_trades > 0) {
            stats.long_average_trade_bps =
                stats.long_net_return_bps / static_cast<double>(stats.long_trades);
            stats.long_win_rate =
                static_cast<double>(stats.long_wins) / static_cast<double>(stats.long_trades);
        }
        if (stats.short_trades > 0) {
            stats.short_average_trade_bps =
                stats.short_net_return_bps / static_cast<double>(stats.short_trades);
            stats.short_win_rate =
                static_cast<double>(stats.short_wins) / static_cast<double>(stats.short_trades);
        }
        stats.sharpe = compute_sharpe(returns_bps);
        return stats;
    }

private:
    bool in_open_window(std::uint64_t timestamp_ns) const
    {
        if (!config_.open_only || session_start_timestamp_ns_ == 0) {
            return true;
        }

        const std::uint64_t window_ns =
            config_.open_window_minutes * 60ULL * 1000000000ULL;
        return timestamp_ns - session_start_timestamp_ns_ <= window_ns;
    }

    void try_open_position(const FeatureEvent& feature, const StrategyOutput& output)
    {
        if (output.signal == SignalState::Neutral) {
            return;
        }

        position_.active = true;
        position_.side = output.signal;
        position_.entry_price = output.signal == SignalState::LongBias
            ? feature.bid_price
            : feature.ask_price;
        position_.entry_sequence = feature.sequence;
        position_.entry_timestamp_ns = feature.timestamp_ns;
    }

    void try_close_position(const FeatureEvent& feature, const StrategyOutput& output)
    {
        const std::uint64_t held_events = feature.sequence - position_.entry_sequence;
        const bool max_hold_reached = held_events >= config_.max_hold_events;
        const double exit_price = position_.side == SignalState::LongBias
            ? feature.ask_price
            : feature.bid_price;
        const double current_gross_return_bps =
            basis_points_return(position_.entry_price, exit_price, position_.side);

        bool should_exit = false;
        if (position_.side == SignalState::LongBias) {
            should_exit = output.score < config_.exit_threshold ||
                          feature.imbalance_100ms < -0.10;
        } else if (position_.side == SignalState::ShortBias) {
            should_exit = output.score > -config_.exit_threshold ||
                          feature.imbalance_100ms > 0.10;
        }

        if (output.signal != SignalState::Neutral && output.signal != position_.side) {
            should_exit = true;
        }

        if (current_gross_return_bps >= config_.take_profit_bps ||
            current_gross_return_bps <= -config_.stop_loss_bps) {
            should_exit = true;
        }

        if (!should_exit && !max_hold_reached) {
            return;
        }

        CompletedTrade trade;
        trade.side = position_.side;
        trade.entry_sequence = position_.entry_sequence;
        trade.exit_sequence = feature.sequence;
        trade.entry_timestamp_ns = position_.entry_timestamp_ns;
        trade.exit_timestamp_ns = feature.timestamp_ns;
        trade.entry_price = position_.entry_price;
        trade.exit_price = exit_price;
        trade.gross_return_bps =
            basis_points_return(trade.entry_price, trade.exit_price, trade.side);
        trade.net_return_bps = trade.gross_return_bps - config_.round_trip_cost_bps;
        trade.holding_events = held_events;

        completed_trades_.push_back(trade);
        position_ = Position{};
    }

    StrategyConfig config_{};
    mutable std::uint64_t session_start_timestamp_ns_ = 0;
    Position position_{};
    StrategyOutput last_output_{};
    std::vector<CompletedTrade> completed_trades_{};
};

inline const char* signal_to_string(SignalState signal)
{
    switch (signal) {
        case SignalState::LongBias:
            return "LONG_BIAS";
        case SignalState::ShortBias:
            return "SHORT_BIAS";
        default:
            return "NEUTRAL";
    }
}

} // namespace mm

namespace liquidity {



struct QuoteEvent
{
    std::uint64_t sequence = 0;
    std::uint64_t source_timestamp_ns = 0;
    std::uint64_t parsed_timestamp_ns = 0;
    double bid_price = 0.0;
    double ask_price = 0.0;
    double bid_size = 0.0;
    double ask_size = 0.0;
    std::array<char, 16> symbol{};
};

struct FeatureEvent
{
    std::uint64_t sequence = 0;
    std::uint64_t timestamp_ns = 0;
    double bid_price = 0.0;
    double ask_price = 0.0;
    double bid_size = 0.0;
    double ask_size = 0.0;
    double mid_price = 0.0;
    double spread_bps_100ms = 0.0;
    double spread_bps_1s = 0.0;
    double imbalance_100ms = 0.0;
    double imbalance_1s = 0.0;
    double microprice_edge_100ms_bps = 0.0;
    double microprice_edge_1s_bps = 0.0;
    double quote_rate_1s = 0.0;
    double avg_bid_size_1s = 0.0;
    double avg_ask_size_1s = 0.0;
};

enum class SignalState : int
{
    Neutral = 0,
    LongBias = 1,
    ShortBias = -1
};

struct FeatureBucket
{
    std::uint64_t bucket_id = 0;
    std::uint32_t quote_count = 0;
    double spread_sum_bps = 0.0;
    double imbalance_sum = 0.0;
    double microprice_edge_sum_bps = 0.0;
    double mid_sum = 0.0;
    double bid_size_sum = 0.0;
    double ask_size_sum = 0.0;
};

struct RollingStats
{
    std::uint32_t quote_count = 0;
    double avg_spread_bps = 0.0;
    double avg_imbalance = 0.0;
    double avg_microprice_edge_bps = 0.0;
    double avg_mid = 0.0;
    double avg_bid_size = 0.0;
    double avg_ask_size = 0.0;
};

class FeatureBuilder
{
public:
    static constexpr std::uint64_t bucket_ns = 100000000ULL;
    static constexpr std::size_t bucket_count = 50;

    bool on_quote(const QuoteEvent& quote, FeatureEvent& feature_out)
    {
        if (quote.ask_price <= quote.bid_price || quote.bid_price <= 0.0) {
            return false;
        }

        const std::uint64_t bucket_id = quote.parsed_timestamp_ns / bucket_ns;
        rotate_to(bucket_id);

        FeatureBucket& bucket = buckets_[bucket_id % bucket_count];
        if (bucket.bucket_id != bucket_id) {
            clear_bucket(bucket, bucket_id);
        }

        const double mid = (quote.bid_price + quote.ask_price) * 0.5;
        const double spread_bps = ((quote.ask_price - quote.bid_price) / mid) * 10000.0;
        const double total_size = quote.bid_size + quote.ask_size;
        const double imbalance = total_size > 0.0
            ? (quote.bid_size - quote.ask_size) / total_size
            : 0.0;
        const double microprice =
            ((quote.ask_price * quote.bid_size) + (quote.bid_price * quote.ask_size)) /
            std::max(total_size, 1e-9);
        const double microprice_edge_bps = ((microprice - mid) / mid) * 10000.0;

        ++bucket.quote_count;
        bucket.spread_sum_bps += spread_bps;
        bucket.imbalance_sum += imbalance;
        bucket.microprice_edge_sum_bps += microprice_edge_bps;
        bucket.mid_sum += mid;
        bucket.bid_size_sum += quote.bid_size;
        bucket.ask_size_sum += quote.ask_size;

        const RollingStats short_window = sum_recent(bucket_id, 1);
        const RollingStats long_window = sum_recent(bucket_id, 10);

        feature_out.sequence = quote.sequence;
        feature_out.timestamp_ns = quote.parsed_timestamp_ns;
        feature_out.bid_price = quote.bid_price;
        feature_out.ask_price = quote.ask_price;
        feature_out.bid_size = quote.bid_size;
        feature_out.ask_size = quote.ask_size;
        feature_out.mid_price = mid;
        feature_out.spread_bps_100ms = short_window.avg_spread_bps;
        feature_out.spread_bps_1s = long_window.avg_spread_bps;
        feature_out.imbalance_100ms = short_window.avg_imbalance;
        feature_out.imbalance_1s = long_window.avg_imbalance;
        feature_out.microprice_edge_100ms_bps = short_window.avg_microprice_edge_bps;
        feature_out.microprice_edge_1s_bps = long_window.avg_microprice_edge_bps;
        feature_out.quote_rate_1s = static_cast<double>(long_window.quote_count);
        feature_out.avg_bid_size_1s = long_window.avg_bid_size;
        feature_out.avg_ask_size_1s = long_window.avg_ask_size;
        return true;
    }

private:
    void clear_bucket(FeatureBucket& bucket, std::uint64_t bucket_id)
    {
        bucket.bucket_id = bucket_id;
        bucket.quote_count = 0;
        bucket.spread_sum_bps = 0.0;
        bucket.imbalance_sum = 0.0;
        bucket.microprice_edge_sum_bps = 0.0;
        bucket.mid_sum = 0.0;
        bucket.bid_size_sum = 0.0;
        bucket.ask_size_sum = 0.0;
    }

    void rotate_to(std::uint64_t bucket_id)
    {
        if (last_bucket_id_ == 0) {
            last_bucket_id_ = bucket_id;
            return;
        }

        if (bucket_id <= last_bucket_id_) {
            return;
        }

        const std::uint64_t distance = bucket_id - last_bucket_id_;
        if (distance >= bucket_count) {
            for (FeatureBucket& bucket : buckets_) {
                clear_bucket(bucket, 0);
            }
        } else {
            for (std::uint64_t step = 1; step <= distance; ++step) {
                clear_bucket(buckets_[(last_bucket_id_ + step) % bucket_count], last_bucket_id_ + step);
            }
        }

        last_bucket_id_ = bucket_id;
    }

    RollingStats sum_recent(std::uint64_t ending_bucket_id, std::size_t window_buckets) const
    {
        RollingStats stats;
        for (std::size_t offset = 0; offset < window_buckets; ++offset) {
            const std::uint64_t bucket_id = ending_bucket_id - offset;
            const FeatureBucket& bucket = buckets_[bucket_id % bucket_count];
            if (bucket.bucket_id != bucket_id || bucket.quote_count == 0) {
                continue;
            }

            stats.quote_count += bucket.quote_count;
            stats.avg_spread_bps += bucket.spread_sum_bps;
            stats.avg_imbalance += bucket.imbalance_sum;
            stats.avg_microprice_edge_bps += bucket.microprice_edge_sum_bps;
            stats.avg_mid += bucket.mid_sum;
            stats.avg_bid_size += bucket.bid_size_sum;
            stats.avg_ask_size += bucket.ask_size_sum;
        }

        if (stats.quote_count > 0) {
            const double count = static_cast<double>(stats.quote_count);
            stats.avg_spread_bps /= count;
            stats.avg_imbalance /= count;
            stats.avg_microprice_edge_bps /= count;
            stats.avg_mid /= count;
            stats.avg_bid_size /= count;
            stats.avg_ask_size /= count;
        }

        return stats;
    }

    std::array<FeatureBucket, bucket_count> buckets_{};
    std::uint64_t last_bucket_id_ = 0;
};

struct StrategyOutput
{
    SignalState signal = SignalState::Neutral;
    double score = 0.0;
    double conviction = 0.0;
    double expected_edge_bps = 0.0;
    double regime_quality = 0.0;
    double size_multiplier = 1.0;
    int archetype = 0;
};

enum class Archetype : int
{
    None = 0,
    PressureFollow = 1,
    BurstFollow = 2,
    TrendFollow = 3,
    FadeExhaustion = 4
};

enum class SessionProfile : int
{
    Unknown = 0,
    Elite = 1,
    Strong = 2,
    Base = 3,
    Skip = 4
};

struct StrategyConfig
{
    double entry_threshold = 1.30;
    double exit_threshold = 0.18;
    double min_spread_bps = 0.06;
    double max_spread_bps = 3.50;
    double min_quote_rate_1s = 28.0;
    double min_expected_edge_bps = 0.24;
    double min_regime_quality = 0.85;
    double min_directional_quality = 0.22;
    std::uint64_t max_hold_events = 8;
    double take_profit_bps = 0.90;
    double stop_loss_bps = 0.65;
    std::uint64_t max_session_signal_count = 60;
    double session_drawdown_stop_bps = 1.25;
    std::uint64_t min_trades_before_session_stop = 5;
    double min_session_average_trade_bps = 0.10;
    double min_open_window_profile_score = 0.18;
    double strong_open_window_profile_score = 0.24;
    double elite_open_window_profile_score = 0.30;
    double max_open_window_signal_flip_ratio = 0.35;
    double max_open_window_profile_stddev = 0.24;
    double min_open_window_direction_consensus = 0.28;
    std::uint64_t min_open_window_signal_count = 4;
    std::uint64_t open_window_profile_warmup_seconds = 120;
    double round_trip_cost_bps = 0.10;
    bool enable_longs = true;
    bool enable_shorts = false;
    bool open_only = true;
    std::uint64_t open_window_minutes = 60;
    Archetype elite_profile_archetype = Archetype::BurstFollow;
    Archetype strong_profile_archetype = Archetype::TrendFollow;
    Archetype base_profile_archetype = Archetype::PressureFollow;
};

struct Position
{
    bool active = false;
    SignalState side = SignalState::Neutral;
    Archetype entry_archetype = Archetype::None;
    double entry_price = 0.0;
    double entry_conviction = 0.0;
    double entry_regime_quality = 0.0;
    double entry_expected_edge_bps = 0.0;
    std::uint64_t entry_sequence = 0;
    std::uint64_t entry_timestamp_ns = 0;
};

struct CompletedTrade
{
    SignalState side = SignalState::Neutral;
    std::uint64_t entry_sequence = 0;
    std::uint64_t exit_sequence = 0;
    std::uint64_t entry_timestamp_ns = 0;
    std::uint64_t exit_timestamp_ns = 0;
    double entry_price = 0.0;
    double exit_price = 0.0;
    double gross_return_bps = 0.0;
    double net_return_bps = 0.0;
    std::uint64_t holding_events = 0;
};

struct StrategyStats
{
    std::uint32_t completed_trades = 0;
    std::uint32_t wins = 0;
    std::uint32_t long_trades = 0;
    std::uint32_t short_trades = 0;
    std::uint32_t long_wins = 0;
    std::uint32_t short_wins = 0;
    double total_net_return_bps = 0.0;
    double average_trade_bps = 0.0;
    double win_rate = 0.0;
    double long_net_return_bps = 0.0;
    double short_net_return_bps = 0.0;
    double long_average_trade_bps = 0.0;
    double short_average_trade_bps = 0.0;
    double long_win_rate = 0.0;
    double short_win_rate = 0.0;
    double max_drawdown_bps = 0.0;
    double sharpe = 0.0;
};

inline double basis_points_return(double entry_price, double exit_price, SignalState side)
{
    if (entry_price <= 0.0 || exit_price <= 0.0 || side == SignalState::Neutral) {
        return 0.0;
    }

    const double raw_return = side == SignalState::LongBias
        ? (exit_price - entry_price) / entry_price
        : (entry_price - exit_price) / entry_price;
    return raw_return * 10000.0;
}

inline double compute_sharpe(const std::vector<double>& returns_bps)
{
    if (returns_bps.size() < 2) {
        return 0.0;
    }

    const double mean =
        std::accumulate(returns_bps.begin(), returns_bps.end(), 0.0) /
        static_cast<double>(returns_bps.size());

    double variance = 0.0;
    for (double value : returns_bps) {
        const double diff = value - mean;
        variance += diff * diff;
    }

    variance /= static_cast<double>(returns_bps.size() - 1);
    const double stddev = std::sqrt(variance);
    if (stddev == 0.0) {
        return 0.0;
    }

    return (mean / stddev) * std::sqrt(static_cast<double>(returns_bps.size()));
}

inline double clamp01(double value)
{
    return std::max(0.0, std::min(1.0, value));
}

inline const char* archetype_to_string(Archetype archetype)
{
    switch (archetype) {
        case Archetype::PressureFollow:
            return "PRESSURE_FOLLOW";
        case Archetype::BurstFollow:
            return "BURST_FOLLOW";
        case Archetype::TrendFollow:
            return "TREND_FOLLOW";
        case Archetype::FadeExhaustion:
            return "FADE_EXHAUSTION";
        case Archetype::None:
        default:
            return "NONE";
    }
}

struct SignalContext
{
    double spread_shock_bps = 0.0;
    double imbalance_impulse = 0.0;
    double microprice_impulse_bps = 0.0;
    double size_skew = 0.0;
    double quote_burst = 0.0;
    double spread_regime_ratio = 0.0;
    double pressure_score = 0.0;
    double burst_score = 0.0;
    double trend_score = 0.0;
    double fade_score = 0.0;
    double expected_edge_bps = 0.0;
    double regime_quality = 0.0;
    double directional_quality = 0.0;
    bool long_context_ok = false;
    bool short_context_ok = false;
    bool spread_ok = false;
    bool liquidity_ok = false;
    bool edge_ok = false;
    bool regime_ok = false;
};

class MicrostructureStrategy
{
public:
    explicit MicrostructureStrategy(StrategyConfig config = {})
        : config_(config),
          active_config_(config)
    {
    }

    void set_session_start_timestamp_ns(std::uint64_t timestamp_ns)
    {
        if (timestamp_ns != 0) {
            session_start_timestamp_ns_ = timestamp_ns;
            session_paused_ = false;
            active_config_ = config_;
            active_open_window_minutes_ = active_config_.open_window_minutes;
            window_profile_samples_ = 0;
            window_profile_score_sum_ = 0.0;
            window_profile_score_sq_sum_ = 0.0;
            window_profile_signal_count_ = 0;
            window_profile_signal_flip_count_ = 0;
            window_profile_direction_sum_ = 0.0;
            window_profile_abs_direction_sum_ = 0.0;
            window_profile_last_signal_ = SignalState::Neutral;
            window_profile_locked_ = false;
            session_regime_ok_ = true;
            selected_profile_ = SessionProfile::Unknown;
            active_archetype_ = Archetype::PressureFollow;
        }
    }

    StrategyOutput evaluate_signal(const FeatureEvent& feature) const
    {
        if (!in_open_window(feature.timestamp_ns)) {
            return {};
        }

        const StrategyConfig& cfg = active_config_;
        const SignalContext context = build_signal_context(feature, cfg);
        StrategyOutput output;
        switch (active_archetype_) {
            case Archetype::BurstFollow:
                output = evaluate_burst_archetype(feature, context, cfg);
                break;
            case Archetype::TrendFollow:
                output = evaluate_trend_archetype(feature, context, cfg);
                break;
            case Archetype::FadeExhaustion:
                output = evaluate_fade_archetype(feature, context, cfg);
                break;
            case Archetype::PressureFollow:
            default:
                output = evaluate_pressure_archetype(feature, context, cfg);
                break;
        }

        update_open_window_profile(feature, output);

        return output;
    }

    void on_feature(const FeatureEvent& feature)
    {
        if (session_start_timestamp_ns_ == 0) {
            session_start_timestamp_ns_ = feature.timestamp_ns;
        }

        const StrategyOutput output = evaluate_signal(feature);

        if (!position_.active) {
            try_open_position(feature, output);
        } else {
            try_close_position(feature, output);
        }

        last_output_ = output;
    }

    const StrategyOutput& last_output() const
    {
        return last_output_;
    }

    const Position& current_position() const
    {
        return position_;
    }

    const std::vector<CompletedTrade>& completed_trades() const
    {
        return completed_trades_;
    }

    std::uint64_t active_open_window_minutes() const
    {
        return active_open_window_minutes_;
    }

    double window_profile_average_score() const
    {
        if (window_profile_samples_ == 0) {
            return 0.0;
        }
        return window_profile_score_sum_ / static_cast<double>(window_profile_samples_);
    }

    double window_profile_score_stddev() const
    {
        if (window_profile_samples_ < 2) {
            return 0.0;
        }

        const double count = static_cast<double>(window_profile_samples_);
        const double mean = window_profile_score_sum_ / count;
        const double mean_square = window_profile_score_sq_sum_ / count;
        const double variance = std::max(0.0, mean_square - (mean * mean));
        return std::sqrt(variance);
    }

    std::uint64_t window_profile_signal_count() const
    {
        return window_profile_signal_count_;
    }

    std::uint64_t window_profile_signal_flip_count() const
    {
        return window_profile_signal_flip_count_;
    }

    StrategyStats stats() const
    {
        StrategyStats stats;
        if (completed_trades_.empty()) {
            return stats;
        }

        std::vector<double> returns_bps;
        double equity_curve = 0.0;
        double peak = 0.0;
        returns_bps.reserve(completed_trades_.size());

        for (const CompletedTrade& trade : completed_trades_) {
            ++stats.completed_trades;
            stats.total_net_return_bps += trade.net_return_bps;
            if (trade.net_return_bps > 0.0) {
                ++stats.wins;
            }
            if (trade.side == SignalState::LongBias) {
                ++stats.long_trades;
                stats.long_net_return_bps += trade.net_return_bps;
                if (trade.net_return_bps > 0.0) {
                    ++stats.long_wins;
                }
            } else if (trade.side == SignalState::ShortBias) {
                ++stats.short_trades;
                stats.short_net_return_bps += trade.net_return_bps;
                if (trade.net_return_bps > 0.0) {
                    ++stats.short_wins;
                }
            }

            equity_curve += trade.net_return_bps;
            peak = std::max(peak, equity_curve);
            stats.max_drawdown_bps = std::max(stats.max_drawdown_bps, peak - equity_curve);
            returns_bps.push_back(trade.net_return_bps);
        }

        stats.average_trade_bps =
            stats.total_net_return_bps / static_cast<double>(completed_trades_.size());
        stats.win_rate =
            static_cast<double>(stats.wins) / static_cast<double>(completed_trades_.size());
        if (stats.long_trades > 0) {
            stats.long_average_trade_bps =
                stats.long_net_return_bps / static_cast<double>(stats.long_trades);
            stats.long_win_rate =
                static_cast<double>(stats.long_wins) / static_cast<double>(stats.long_trades);
        }
        if (stats.short_trades > 0) {
            stats.short_average_trade_bps =
                stats.short_net_return_bps / static_cast<double>(stats.short_trades);
            stats.short_win_rate =
                static_cast<double>(stats.short_wins) / static_cast<double>(stats.short_trades);
        }
        stats.sharpe = compute_sharpe(returns_bps);
        return stats;
    }

private:
    SignalContext build_signal_context(const FeatureEvent& feature, const StrategyConfig& cfg) const
    {
        SignalContext context;
        context.spread_shock_bps =
            std::max(0.0, feature.spread_bps_100ms - std::max(feature.spread_bps_1s, cfg.min_spread_bps));
        context.imbalance_impulse = feature.imbalance_100ms - feature.imbalance_1s;
        context.microprice_impulse_bps =
            feature.microprice_edge_100ms_bps - feature.microprice_edge_1s_bps;
        context.size_skew =
            (feature.avg_bid_size_1s - feature.avg_ask_size_1s) /
            std::max(feature.avg_bid_size_1s + feature.avg_ask_size_1s, 1e-9);
        context.quote_burst =
            std::max(0.0,
                     (feature.quote_rate_1s - cfg.min_quote_rate_1s) /
                         std::max(cfg.min_quote_rate_1s, 1.0));
        context.spread_regime_ratio =
            feature.spread_bps_100ms / std::max(feature.spread_bps_1s, cfg.min_spread_bps);
        context.pressure_score =
            (feature.imbalance_100ms * 0.42) +
            (context.imbalance_impulse * 0.34) +
            (feature.microprice_edge_100ms_bps * 0.18) +
            (context.microprice_impulse_bps * 0.20) +
            (context.size_skew * 0.08);
        context.burst_score =
            (context.spread_shock_bps * 0.42) +
            (std::abs(context.imbalance_impulse) * 0.95) +
            (std::abs(context.microprice_impulse_bps) * 0.34) +
            (context.quote_burst * 0.70) +
            (std::abs(feature.microprice_edge_100ms_bps) * 0.10);
        context.trend_score =
            (feature.imbalance_1s * 0.42) +
            (feature.imbalance_100ms * 0.18) +
            (feature.microprice_edge_1s_bps * 0.26) +
            (feature.microprice_edge_100ms_bps * 0.10) +
            (context.size_skew * 0.10) +
            (context.quote_burst * 0.14);
        context.fade_score =
            (-feature.imbalance_1s * 0.30) +
            (context.imbalance_impulse * 0.34) +
            (-feature.microprice_edge_1s_bps * 0.24) +
            (context.microprice_impulse_bps * 0.28) +
            (-feature.imbalance_100ms * 0.10) +
            (-feature.microprice_edge_100ms_bps * 0.08);
        context.expected_edge_bps =
            (context.burst_score * 0.44) +
            (std::abs(context.fade_score) * 0.12) +
            (std::abs(feature.microprice_edge_100ms_bps) * 0.24) +
            (std::abs(feature.microprice_edge_1s_bps) * 0.14) +
            (feature.spread_bps_100ms * 0.10);
        context.regime_quality =
            (context.quote_burst * 0.35) +
            (std::max(0.0, context.spread_regime_ratio - 1.0) * 0.45) +
            (std::abs(context.imbalance_impulse) * 1.05) +
            (std::abs(context.microprice_impulse_bps) * 0.55) +
            (std::abs(feature.microprice_edge_100ms_bps) * 0.08);
        context.directional_quality =
            (std::abs(context.pressure_score) * 0.80) +
            (std::abs(context.fade_score) * 0.12) +
            (std::abs(feature.microprice_edge_100ms_bps) * 0.18) +
            (std::abs(feature.imbalance_100ms) * 0.35);
        context.long_context_ok =
            feature.imbalance_1s >= -0.03 &&
            feature.microprice_edge_1s_bps >= -0.04;
        context.short_context_ok =
            feature.imbalance_1s <= 0.03 &&
            feature.microprice_edge_1s_bps <= 0.04;
        context.spread_ok =
            feature.spread_bps_100ms >= cfg.min_spread_bps &&
            feature.spread_bps_100ms <= cfg.max_spread_bps;
        context.liquidity_ok = feature.quote_rate_1s >= cfg.min_quote_rate_1s;
        context.edge_ok =
            context.expected_edge_bps >= std::max(cfg.min_expected_edge_bps,
                                                  cfg.round_trip_cost_bps + (feature.spread_bps_100ms * 0.10));
        context.regime_ok =
            context.regime_quality >= cfg.min_regime_quality &&
            context.directional_quality >= cfg.min_directional_quality &&
            feature.spread_bps_100ms <= (feature.spread_bps_1s + 1.75);
        return context;
    }

    StrategyOutput make_output(Archetype archetype,
                               double score,
                               double activation_score,
                               const SignalContext& context) const
    {
        StrategyOutput output;
        output.archetype = static_cast<int>(archetype);
        output.score = score;
        output.conviction = std::min(1.0, std::max(std::abs(score), activation_score) / 1.40);
        output.expected_edge_bps = context.expected_edge_bps;
        output.regime_quality = context.regime_quality;
        const double normalized_regime_quality = clamp01(context.regime_quality / 1.50);
        output.size_multiplier =
            0.35 + (0.65 * clamp01((output.conviction * 0.75) + (normalized_regime_quality * 0.25)));
        return output;
    }

    StrategyOutput evaluate_pressure_archetype(const FeatureEvent& feature,
                                               const SignalContext& context,
                                               const StrategyConfig& cfg) const
    {
        StrategyOutput output =
            make_output(Archetype::PressureFollow, context.pressure_score, context.burst_score, context);

        const bool stress_detected =
            context.burst_score >= cfg.entry_threshold &&
            context.quote_burst >= 0.10 &&
            context.spread_regime_ratio >= 1.08 &&
            std::abs(context.imbalance_impulse) >= 0.12 &&
            std::abs(context.microprice_impulse_bps) >= 0.08;
        if (!context.spread_ok || !context.liquidity_ok || !context.edge_ok || !stress_detected ||
            !context.regime_ok) {
            return output;
        }

        const bool long_alignment =
            context.pressure_score >= 0.26 &&
            feature.imbalance_100ms >= 0.12 &&
            context.imbalance_impulse >= 0.12 &&
            context.microprice_impulse_bps >= 0.08 &&
            feature.microprice_edge_100ms_bps >= 0.05 &&
            context.long_context_ok;
        const bool short_alignment =
            context.pressure_score <= -0.26 &&
            feature.imbalance_100ms <= -0.12 &&
            context.imbalance_impulse <= -0.12 &&
            context.microprice_impulse_bps <= -0.08 &&
            feature.microprice_edge_100ms_bps <= -0.05 &&
            context.short_context_ok;

        if (cfg.enable_longs && long_alignment) {
            output.signal = SignalState::LongBias;
        } else if (cfg.enable_shorts && short_alignment) {
            output.signal = SignalState::ShortBias;
        }

        return output;
    }

    StrategyOutput evaluate_burst_archetype(const FeatureEvent& feature,
                                            const SignalContext& context,
                                            const StrategyConfig& cfg) const
    {
        const double burst_direction_score =
            (feature.imbalance_100ms * 0.30) +
            (context.imbalance_impulse * 0.38) +
            (context.microprice_impulse_bps * 0.26) +
            (feature.microprice_edge_100ms_bps * 0.14);
        StrategyOutput output =
            make_output(Archetype::BurstFollow, burst_direction_score, context.burst_score, context);

        const bool stress_detected =
            context.burst_score >= (cfg.entry_threshold * 0.92) &&
            context.quote_burst >= 0.18 &&
            context.spread_regime_ratio >= 1.12 &&
            std::abs(context.imbalance_impulse) >= 0.16 &&
            std::abs(context.microprice_impulse_bps) >= 0.10;
        if (!context.spread_ok || !context.liquidity_ok || !context.edge_ok || !stress_detected ||
            !context.regime_ok) {
            return output;
        }

        const bool long_alignment =
            burst_direction_score >= 0.20 &&
            feature.imbalance_100ms >= 0.14 &&
            context.imbalance_impulse >= 0.16 &&
            context.microprice_impulse_bps >= 0.10 &&
            feature.microprice_edge_100ms_bps >= 0.06 &&
            context.long_context_ok;
        const bool short_alignment =
            burst_direction_score <= -0.20 &&
            feature.imbalance_100ms <= -0.14 &&
            context.imbalance_impulse <= -0.16 &&
            context.microprice_impulse_bps <= -0.10 &&
            feature.microprice_edge_100ms_bps <= -0.06 &&
            context.short_context_ok;

        if (cfg.enable_longs && long_alignment) {
            output.signal = SignalState::LongBias;
        } else if (cfg.enable_shorts && short_alignment) {
            output.signal = SignalState::ShortBias;
        }

        return output;
    }

    StrategyOutput evaluate_trend_archetype(const FeatureEvent& feature,
                                            const SignalContext& context,
                                            const StrategyConfig& cfg) const
    {
        StrategyOutput output =
            make_output(Archetype::TrendFollow, context.trend_score, std::abs(context.trend_score), context);

        const bool trend_regime_ok =
            context.regime_ok &&
            context.quote_burst >= 0.04 &&
            std::abs(feature.imbalance_1s) >= 0.08 &&
            std::abs(feature.microprice_edge_1s_bps) >= 0.04;
        if (!context.spread_ok || !context.liquidity_ok || !context.edge_ok || !trend_regime_ok) {
            return output;
        }

        const bool long_alignment =
            context.trend_score >= (cfg.entry_threshold * 0.22) &&
            feature.imbalance_1s >= 0.08 &&
            feature.microprice_edge_1s_bps >= 0.04 &&
            feature.imbalance_100ms >= -0.02 &&
            feature.microprice_edge_100ms_bps >= -0.02 &&
            context.long_context_ok;
        const bool short_alignment =
            context.trend_score <= -(cfg.entry_threshold * 0.22) &&
            feature.imbalance_1s <= -0.08 &&
            feature.microprice_edge_1s_bps <= -0.04 &&
            feature.imbalance_100ms <= 0.02 &&
            feature.microprice_edge_100ms_bps <= 0.02 &&
            context.short_context_ok;

        if (cfg.enable_longs && long_alignment) {
            output.signal = SignalState::LongBias;
        } else if (cfg.enable_shorts && short_alignment) {
            output.signal = SignalState::ShortBias;
        }

        return output;
    }

    StrategyOutput evaluate_fade_archetype(const FeatureEvent& feature,
                                           const SignalContext& context,
                                           const StrategyConfig& cfg) const
    {
        StrategyOutput output =
            make_output(Archetype::FadeExhaustion, context.fade_score, std::abs(context.fade_score), context);

        const bool exhaustion_regime_ok =
            context.quote_burst >= 0.08 &&
            context.spread_regime_ratio >= 1.05 &&
            context.burst_score >= (cfg.entry_threshold * 0.78) &&
            std::abs(feature.imbalance_1s) >= 0.10 &&
            std::abs(feature.microprice_edge_1s_bps) >= 0.05 &&
            std::abs(context.imbalance_impulse) >= 0.10 &&
            std::abs(context.microprice_impulse_bps) >= 0.08;
        if (!context.spread_ok || !context.liquidity_ok || !context.edge_ok || !exhaustion_regime_ok) {
            return output;
        }

        const bool long_alignment =
            context.fade_score >= (cfg.entry_threshold * 0.16) &&
            feature.imbalance_1s <= -0.10 &&
            feature.microprice_edge_1s_bps <= -0.05 &&
            context.imbalance_impulse >= 0.10 &&
            context.microprice_impulse_bps >= 0.08 &&
            feature.imbalance_100ms >= (feature.imbalance_1s + 0.08) &&
            feature.microprice_edge_100ms_bps >= (feature.microprice_edge_1s_bps + 0.05);
        const bool short_alignment =
            context.fade_score <= -(cfg.entry_threshold * 0.16) &&
            feature.imbalance_1s >= 0.10 &&
            feature.microprice_edge_1s_bps >= 0.05 &&
            context.imbalance_impulse <= -0.10 &&
            context.microprice_impulse_bps <= -0.08 &&
            feature.imbalance_100ms <= (feature.imbalance_1s - 0.08) &&
            feature.microprice_edge_100ms_bps <= (feature.microprice_edge_1s_bps - 0.05);

        if (cfg.enable_longs && long_alignment) {
            output.signal = SignalState::LongBias;
        } else if (cfg.enable_shorts && short_alignment) {
            output.signal = SignalState::ShortBias;
        }

        return output;
    }

    void apply_session_profile(SessionProfile profile) const
    {
        active_config_ = config_;
        switch (profile) {
            case SessionProfile::Elite:
                active_archetype_ = config_.elite_profile_archetype;
                active_config_.entry_threshold = 0.90;
                active_config_.min_spread_bps = 0.06;
                active_config_.min_quote_rate_1s = 34.0;
                active_config_.min_expected_edge_bps = 0.24;
                active_config_.min_regime_quality = 0.85;
                active_config_.min_directional_quality = 0.22;
                active_config_.max_hold_events = 16;
                active_config_.take_profit_bps = 1.05;
                active_config_.stop_loss_bps = 0.50;
                active_config_.open_window_minutes = 75;
                break;
            case SessionProfile::Strong:
                active_archetype_ = config_.strong_profile_archetype;
                active_config_.entry_threshold = 1.10;
                active_config_.min_spread_bps = 0.06;
                active_config_.min_quote_rate_1s = 34.0;
                active_config_.min_expected_edge_bps = 0.24;
                active_config_.min_regime_quality = 0.85;
                active_config_.min_directional_quality = 0.22;
                active_config_.max_hold_events = 16;
                active_config_.take_profit_bps = 1.00;
                active_config_.stop_loss_bps = 0.55;
                active_config_.open_window_minutes = 60;
                break;
            case SessionProfile::Base:
                active_archetype_ = config_.base_profile_archetype;
                active_config_.entry_threshold = 1.30;
                active_config_.min_spread_bps = 0.06;
                active_config_.min_quote_rate_1s = 28.0;
                active_config_.min_expected_edge_bps = 0.24;
                active_config_.min_regime_quality = 0.85;
                active_config_.min_directional_quality = 0.22;
                active_config_.max_hold_events = 8;
                active_config_.take_profit_bps = 0.90;
                active_config_.stop_loss_bps = 0.55;
                active_config_.open_window_minutes = 60;
                break;
            case SessionProfile::Skip:
            case SessionProfile::Unknown:
            default:
                active_archetype_ = Archetype::None;
                break;
        }

        if (active_archetype_ == Archetype::FadeExhaustion) {
            active_config_.entry_threshold *= 0.88;
            active_config_.min_expected_edge_bps = std::max(active_config_.min_expected_edge_bps, 0.26);
            active_config_.max_hold_events =
                std::max<std::uint64_t>(6, std::min<std::uint64_t>(active_config_.max_hold_events, 10));
            active_config_.take_profit_bps *= 0.88;
            active_config_.stop_loss_bps *= 0.78;
            active_config_.open_window_minutes =
                std::min<std::uint64_t>(active_config_.open_window_minutes, 45);
        }
    }

    void update_open_window_profile(const FeatureEvent& feature, const StrategyOutput& output) const
    {
        const StrategyConfig& cfg = active_config_;

        if (!cfg.open_only || session_start_timestamp_ns_ == 0 || window_profile_locked_) {
            return;
        }

        const std::uint64_t warmup_ns =
            cfg.open_window_profile_warmup_seconds * 1000000000ULL;
        const std::uint64_t elapsed_ns =
            feature.timestamp_ns > session_start_timestamp_ns_
                ? (feature.timestamp_ns - session_start_timestamp_ns_)
                : 0ULL;

        const double spread_shock_bps =
            std::max(0.0, feature.spread_bps_100ms - std::max(feature.spread_bps_1s, cfg.min_spread_bps));
        const double imbalance_impulse = feature.imbalance_100ms - feature.imbalance_1s;
        const double microprice_impulse_bps =
            feature.microprice_edge_100ms_bps - feature.microprice_edge_1s_bps;
        const double size_skew =
            (feature.avg_bid_size_1s - feature.avg_ask_size_1s) /
            std::max(feature.avg_bid_size_1s + feature.avg_ask_size_1s, 1e-9);
        const double quote_burst =
            std::max(0.0,
                     (feature.quote_rate_1s - cfg.min_quote_rate_1s) /
                         std::max(cfg.min_quote_rate_1s, 1.0));

        const double burst_score =
            (clamp01(quote_burst / 0.40) * 0.30) +
            (clamp01(spread_shock_bps / 0.25) * 0.20) +
            (clamp01(std::abs(imbalance_impulse) / 0.18) * 0.20) +
            (clamp01(std::abs(microprice_impulse_bps) / 0.12) * 0.20) +
            (clamp01(std::abs(size_skew) / 0.20) * 0.10);

        ++window_profile_samples_;
        window_profile_score_sum_ += burst_score;
        window_profile_score_sq_sum_ += burst_score * burst_score;
        window_profile_direction_sum_ += output.score;
        window_profile_abs_direction_sum_ += std::abs(output.score);
        if (output.signal != SignalState::Neutral) {
            ++window_profile_signal_count_;
            if (window_profile_last_signal_ != SignalState::Neutral &&
                window_profile_last_signal_ != output.signal) {
                ++window_profile_signal_flip_count_;
            }
            window_profile_last_signal_ = output.signal;
        }

        if (elapsed_ns < warmup_ns) {
            return;
        }

        if (window_profile_signal_count_ >= cfg.max_session_signal_count) {
            session_paused_ = true;
        }

        const double average_profile_score = window_profile_average_score();
        const double profile_score_stddev = window_profile_score_stddev();
        const double signal_flip_ratio = window_profile_signal_count_ > 0
            ? static_cast<double>(window_profile_signal_flip_count_) /
                  static_cast<double>(window_profile_signal_count_)
            : 0.0;
        const double direction_consensus = window_profile_abs_direction_sum_ > 0.0
            ? std::abs(window_profile_direction_sum_) / window_profile_abs_direction_sum_
            : 0.0;
        const bool enough_signals =
            window_profile_signal_count_ >= cfg.min_open_window_signal_count;

        // Use the opening warmup to choose an aggressive band or skip noisy sessions.
        if (enough_signals &&
            average_profile_score >= cfg.elite_open_window_profile_score &&
            profile_score_stddev <= 0.18 &&
            signal_flip_ratio <= 0.18 &&
            direction_consensus >= 0.55) {
            selected_profile_ = SessionProfile::Elite;
            apply_session_profile(selected_profile_);
            session_regime_ok_ = true;
        } else if (enough_signals &&
                   average_profile_score >= cfg.strong_open_window_profile_score &&
                   profile_score_stddev <= 0.20 &&
                   signal_flip_ratio <= 0.24 &&
                   direction_consensus >= 0.42) {
            selected_profile_ = SessionProfile::Strong;
            apply_session_profile(selected_profile_);
            session_regime_ok_ = true;
        } else if (average_profile_score >= cfg.min_open_window_profile_score &&
                   profile_score_stddev <= cfg.max_open_window_profile_stddev &&
                   signal_flip_ratio <= cfg.max_open_window_signal_flip_ratio &&
                   direction_consensus >= cfg.min_open_window_direction_consensus) {
            selected_profile_ = SessionProfile::Base;
            apply_session_profile(selected_profile_);
            session_regime_ok_ = true;
        } else {
            selected_profile_ = SessionProfile::Skip;
            session_regime_ok_ = false;
            session_paused_ = true;
        }

        active_open_window_minutes_ = active_config_.open_window_minutes;

        window_profile_locked_ = true;
    }

    bool in_open_window(std::uint64_t timestamp_ns) const
    {
        if (!active_config_.open_only || session_start_timestamp_ns_ == 0) {
            return true;
        }

        const std::uint64_t window_ns =
            active_open_window_minutes_ * 60ULL * 1000000000ULL;
        return timestamp_ns - session_start_timestamp_ns_ <= window_ns;
    }

    void try_open_position(const FeatureEvent& feature, const StrategyOutput& output)
    {
        if (session_paused_ || !session_regime_ok_ || !window_profile_locked_ ||
            output.signal == SignalState::Neutral) {
            return;
        }

        position_.active = true;
        position_.side = output.signal;
        position_.entry_archetype = static_cast<Archetype>(output.archetype);
        position_.entry_price = output.signal == SignalState::LongBias
            ? feature.ask_price
            : feature.bid_price;
        position_.entry_conviction = output.conviction;
        position_.entry_regime_quality = output.regime_quality;
        position_.entry_expected_edge_bps = output.expected_edge_bps;
        position_.entry_sequence = feature.sequence;
        position_.entry_timestamp_ns = feature.timestamp_ns;
    }

    void try_close_position(const FeatureEvent& feature, const StrategyOutput& output)
    {
        const StrategyConfig& cfg = active_config_;
        const std::uint64_t held_events = feature.sequence - position_.entry_sequence;
        const double entry_conviction = clamp01(position_.entry_conviction);
        const double entry_regime_quality = clamp01(position_.entry_regime_quality / 1.50);
        const double dynamic_exit_threshold =
            cfg.exit_threshold +
            (0.10 * (1.0 - entry_conviction)) +
            (0.05 * std::max(0.0, 0.88 - entry_regime_quality));
        const double dynamic_take_profit_bps =
            cfg.take_profit_bps * (0.90 + (0.18 * entry_conviction));
        const double dynamic_stop_loss_bps =
            cfg.stop_loss_bps * (0.85 + (0.20 * entry_conviction));
        std::uint64_t dynamic_max_hold_events =
            cfg.max_hold_events + static_cast<std::uint64_t>(std::llround(entry_conviction * 3.0));
        const double exit_price = position_.side == SignalState::LongBias
            ? feature.bid_price
            : feature.ask_price;
        const double current_gross_return_bps =
            basis_points_return(position_.entry_price, exit_price, position_.side);
        double archetype_exit_threshold = dynamic_exit_threshold;
        double archetype_take_profit_bps = dynamic_take_profit_bps;
        double archetype_stop_loss_bps = dynamic_stop_loss_bps;

        switch (position_.entry_archetype) {
            case Archetype::BurstFollow:
                archetype_exit_threshold += 0.06;
                archetype_take_profit_bps *= 0.95;
                archetype_stop_loss_bps *= 0.82;
                dynamic_max_hold_events = std::max<std::uint64_t>(4, dynamic_max_hold_events - 4);
                break;
            case Archetype::TrendFollow:
                archetype_exit_threshold *= 0.72;
                archetype_take_profit_bps *= 1.12;
                archetype_stop_loss_bps *= 1.04;
                dynamic_max_hold_events += 4;
                break;
            case Archetype::FadeExhaustion:
                archetype_exit_threshold += 0.12;
                archetype_take_profit_bps *= 0.88;
                archetype_stop_loss_bps *= 0.74;
                dynamic_max_hold_events = std::max<std::uint64_t>(4, dynamic_max_hold_events - 3);
                break;
            case Archetype::PressureFollow:
            case Archetype::None:
            default:
                break;
        }

        bool should_exit = false;
        if (position_.side == SignalState::LongBias) {
            should_exit =
                output.score < archetype_exit_threshold ||
                feature.imbalance_100ms < -0.06 ||
                feature.microprice_edge_100ms_bps < -0.05 ||
                output.expected_edge_bps < (std::max(cfg.min_expected_edge_bps,
                                                      position_.entry_expected_edge_bps * 0.70));
            if (position_.entry_archetype == Archetype::TrendFollow) {
                should_exit = should_exit ||
                    feature.imbalance_1s < -0.04 ||
                    feature.microprice_edge_1s_bps < -0.04;
            } else if (position_.entry_archetype == Archetype::FadeExhaustion) {
                should_exit = should_exit ||
                    feature.imbalance_100ms <= feature.imbalance_1s ||
                    feature.microprice_edge_100ms_bps <= feature.microprice_edge_1s_bps;
            }
        } else if (position_.side == SignalState::ShortBias) {
            should_exit =
                output.score > -archetype_exit_threshold ||
                feature.imbalance_100ms > 0.06 ||
                feature.microprice_edge_100ms_bps > 0.05 ||
                output.expected_edge_bps < (std::max(cfg.min_expected_edge_bps,
                                                      position_.entry_expected_edge_bps * 0.70));
            if (position_.entry_archetype == Archetype::TrendFollow) {
                should_exit = should_exit ||
                    feature.imbalance_1s > 0.04 ||
                    feature.microprice_edge_1s_bps > 0.04;
            } else if (position_.entry_archetype == Archetype::FadeExhaustion) {
                should_exit = should_exit ||
                    feature.imbalance_100ms >= feature.imbalance_1s ||
                    feature.microprice_edge_100ms_bps >= feature.microprice_edge_1s_bps;
            }
        }

        if (output.signal != SignalState::Neutral && output.signal != position_.side) {
            should_exit = true;
        }

        if (current_gross_return_bps >= archetype_take_profit_bps ||
            current_gross_return_bps <= -archetype_stop_loss_bps ||
            held_events >= dynamic_max_hold_events) {
            should_exit = true;
        }

        if (!should_exit) {
            return;
        }

        CompletedTrade trade;
        trade.side = position_.side;
        trade.entry_sequence = position_.entry_sequence;
        trade.exit_sequence = feature.sequence;
        trade.entry_timestamp_ns = position_.entry_timestamp_ns;
        trade.exit_timestamp_ns = feature.timestamp_ns;
        trade.entry_price = position_.entry_price;
        trade.exit_price = exit_price;
        trade.gross_return_bps =
            basis_points_return(trade.entry_price, trade.exit_price, trade.side);
        trade.net_return_bps = trade.gross_return_bps - cfg.round_trip_cost_bps;
        trade.holding_events = held_events;

        completed_trades_.push_back(trade);
        ++session_closed_trades_;
        session_equity_bps_ += trade.net_return_bps;
        session_peak_equity_bps_ = std::max(session_peak_equity_bps_, session_equity_bps_);
        if (trade.net_return_bps > 0.0) {
            session_consecutive_losses_ = 0;
        } else {
            ++session_consecutive_losses_;
        }
        const double session_average_trade_bps =
            session_equity_bps_ / static_cast<double>(session_closed_trades_);
        const double session_drawdown_bps = session_peak_equity_bps_ - session_equity_bps_;
        if (session_closed_trades_ >= active_config_.min_trades_before_session_stop &&
            (session_equity_bps_ <= 0.0 ||
             session_consecutive_losses_ >= 2 ||
             session_drawdown_bps >= active_config_.session_drawdown_stop_bps ||
             session_average_trade_bps < active_config_.min_session_average_trade_bps)) {
            session_paused_ = true;
        }
        position_ = Position{};
    }

    StrategyConfig config_{}; 
    mutable StrategyConfig active_config_{};
    mutable std::uint64_t session_start_timestamp_ns_ = 0;
    mutable std::uint64_t active_open_window_minutes_ = 45;
    mutable std::uint64_t window_profile_samples_ = 0;
    mutable double window_profile_score_sum_ = 0.0;
    mutable double window_profile_score_sq_sum_ = 0.0;
    mutable std::uint64_t window_profile_signal_count_ = 0;
    mutable std::uint64_t window_profile_signal_flip_count_ = 0;
    mutable double window_profile_direction_sum_ = 0.0;
    mutable double window_profile_abs_direction_sum_ = 0.0;
    mutable SignalState window_profile_last_signal_ = SignalState::Neutral;
    mutable bool window_profile_locked_ = false;
    mutable bool session_regime_ok_ = true;
    mutable SessionProfile selected_profile_ = SessionProfile::Unknown;
    mutable Archetype active_archetype_ = Archetype::PressureFollow;
    Position position_{};
    StrategyOutput last_output_{};
    std::vector<CompletedTrade> completed_trades_{};
    double session_equity_bps_ = 0.0;
    double session_peak_equity_bps_ = 0.0;
    std::uint64_t session_closed_trades_ = 0;
    std::uint64_t session_consecutive_losses_ = 0;
    mutable bool session_paused_ = false;
};

inline const char* signal_to_string(SignalState signal)
{
    switch (signal) {
        case SignalState::LongBias:
            return "LONG_BIAS";
        case SignalState::ShortBias:
            return "SHORT_BIAS";
        default:
            return "NEUTRAL";
    }
}

} // namespace liquidity

namespace momentum {



struct QuoteEvent
{
    std::uint64_t sequence = 0;
    std::uint64_t source_timestamp_ns = 0;
    std::uint64_t parsed_timestamp_ns = 0;
    double bid_price = 0.0;
    double ask_price = 0.0;
    double bid_size = 0.0;
    double ask_size = 0.0;
    std::array<char, 16> symbol{};
};

struct FeatureEvent
{
    std::uint64_t sequence = 0;
    std::uint64_t timestamp_ns = 0;
    double bid_price = 0.0;
    double ask_price = 0.0;
    double bid_size = 0.0;
    double ask_size = 0.0;
    double mid_price = 0.0;
    double spread_bps_100ms = 0.0;
    double spread_bps_1s = 0.0;
    double imbalance_100ms = 0.0;
    double imbalance_1s = 0.0;
    double microprice_edge_100ms_bps = 0.0;
    double microprice_edge_1s_bps = 0.0;
    double quote_rate_1s = 0.0;
    double avg_bid_size_1s = 0.0;
    double avg_ask_size_1s = 0.0;
};

enum class SignalState : int
{
    Neutral = 0,
    LongBias = 1,
    ShortBias = -1
};

struct FeatureBucket
{
    std::uint64_t bucket_id = 0;
    std::uint32_t quote_count = 0;
    double spread_sum_bps = 0.0;
    double imbalance_sum = 0.0;
    double microprice_edge_sum_bps = 0.0;
    double mid_sum = 0.0;
    double bid_size_sum = 0.0;
    double ask_size_sum = 0.0;
};

struct RollingStats
{
    std::uint32_t quote_count = 0;
    double avg_spread_bps = 0.0;
    double avg_imbalance = 0.0;
    double avg_microprice_edge_bps = 0.0;
    double avg_mid = 0.0;
    double avg_bid_size = 0.0;
    double avg_ask_size = 0.0;
};

class FeatureBuilder
{
public:
    static constexpr std::uint64_t bucket_ns = 100000000ULL;
    static constexpr std::size_t bucket_count = 50;

    bool on_quote(const QuoteEvent& quote, FeatureEvent& feature_out)
    {
        if (quote.ask_price <= quote.bid_price || quote.bid_price <= 0.0) {
            return false;
        }

        const std::uint64_t bucket_id = quote.parsed_timestamp_ns / bucket_ns;
        rotate_to(bucket_id);

        FeatureBucket& bucket = buckets_[bucket_id % bucket_count];
        if (bucket.bucket_id != bucket_id) {
            clear_bucket(bucket, bucket_id);
        }

        const double mid = (quote.bid_price + quote.ask_price) * 0.5;
        const double spread_bps = ((quote.ask_price - quote.bid_price) / mid) * 10000.0;
        const double total_size = quote.bid_size + quote.ask_size;
        const double imbalance = total_size > 0.0
            ? (quote.bid_size - quote.ask_size) / total_size
            : 0.0;
        const double microprice =
            ((quote.ask_price * quote.bid_size) + (quote.bid_price * quote.ask_size)) /
            std::max(total_size, 1e-9);
        const double microprice_edge_bps = ((microprice - mid) / mid) * 10000.0;

        ++bucket.quote_count;
        bucket.spread_sum_bps += spread_bps;
        bucket.imbalance_sum += imbalance;
        bucket.microprice_edge_sum_bps += microprice_edge_bps;
        bucket.mid_sum += mid;
        bucket.bid_size_sum += quote.bid_size;
        bucket.ask_size_sum += quote.ask_size;

        const RollingStats short_window = sum_recent(bucket_id, 1);
        const RollingStats long_window = sum_recent(bucket_id, 10);

        feature_out.sequence = quote.sequence;
        feature_out.timestamp_ns = quote.parsed_timestamp_ns;
        feature_out.bid_price = quote.bid_price;
        feature_out.ask_price = quote.ask_price;
        feature_out.bid_size = quote.bid_size;
        feature_out.ask_size = quote.ask_size;
        feature_out.mid_price = mid;
        feature_out.spread_bps_100ms = short_window.avg_spread_bps;
        feature_out.spread_bps_1s = long_window.avg_spread_bps;
        feature_out.imbalance_100ms = short_window.avg_imbalance;
        feature_out.imbalance_1s = long_window.avg_imbalance;
        feature_out.microprice_edge_100ms_bps = short_window.avg_microprice_edge_bps;
        feature_out.microprice_edge_1s_bps = long_window.avg_microprice_edge_bps;
        feature_out.quote_rate_1s = static_cast<double>(long_window.quote_count);
        feature_out.avg_bid_size_1s = long_window.avg_bid_size;
        feature_out.avg_ask_size_1s = long_window.avg_ask_size;
        return true;
    }

private:
    void clear_bucket(FeatureBucket& bucket, std::uint64_t bucket_id)
    {
        bucket.bucket_id = bucket_id;
        bucket.quote_count = 0;
        bucket.spread_sum_bps = 0.0;
        bucket.imbalance_sum = 0.0;
        bucket.microprice_edge_sum_bps = 0.0;
        bucket.mid_sum = 0.0;
        bucket.bid_size_sum = 0.0;
        bucket.ask_size_sum = 0.0;
    }

    void rotate_to(std::uint64_t bucket_id)
    {
        if (last_bucket_id_ == 0) {
            last_bucket_id_ = bucket_id;
            return;
        }

        if (bucket_id <= last_bucket_id_) {
            return;
        }

        const std::uint64_t distance = bucket_id - last_bucket_id_;
        if (distance >= bucket_count) {
            for (FeatureBucket& bucket : buckets_) {
                clear_bucket(bucket, 0);
            }
        } else {
            for (std::uint64_t step = 1; step <= distance; ++step) {
                clear_bucket(buckets_[(last_bucket_id_ + step) % bucket_count], last_bucket_id_ + step);
            }
        }

        last_bucket_id_ = bucket_id;
    }

    RollingStats sum_recent(std::uint64_t ending_bucket_id, std::size_t window_buckets) const
    {
        RollingStats stats;
        for (std::size_t offset = 0; offset < window_buckets; ++offset) {
            const std::uint64_t bucket_id = ending_bucket_id - offset;
            const FeatureBucket& bucket = buckets_[bucket_id % bucket_count];
            if (bucket.bucket_id != bucket_id || bucket.quote_count == 0) {
                continue;
            }

            stats.quote_count += bucket.quote_count;
            stats.avg_spread_bps += bucket.spread_sum_bps;
            stats.avg_imbalance += bucket.imbalance_sum;
            stats.avg_microprice_edge_bps += bucket.microprice_edge_sum_bps;
            stats.avg_mid += bucket.mid_sum;
            stats.avg_bid_size += bucket.bid_size_sum;
            stats.avg_ask_size += bucket.ask_size_sum;
        }

        if (stats.quote_count > 0) {
            const double count = static_cast<double>(stats.quote_count);
            stats.avg_spread_bps /= count;
            stats.avg_imbalance /= count;
            stats.avg_microprice_edge_bps /= count;
            stats.avg_mid /= count;
            stats.avg_bid_size /= count;
            stats.avg_ask_size /= count;
        }

        return stats;
    }

    std::array<FeatureBucket, bucket_count> buckets_{};
    std::uint64_t last_bucket_id_ = 0;
};

struct StrategyOutput
{
    SignalState signal = SignalState::Neutral;
    double score = 0.0;
    double conviction = 0.0;
    double expected_edge_bps = 0.0;
    double regime_quality = 0.0;
    double size_multiplier = 1.0;
};

enum class SessionProfile : int
{
    Unknown = 0,
    Strong = 1,
    Base = 2,
    Skip = 3
};

struct StrategyConfig
{
    double entry_threshold = 1.25;
    double exit_threshold = 0.18;
    double min_spread_bps = 0.10;
    double max_spread_bps = 3.50;
    double min_quote_rate_1s = 32.0;
    double min_expected_edge_bps = 0.28;
    double min_regime_quality = 0.95;
    double min_directional_quality = 0.28;
    std::uint64_t max_hold_events = 7;
    double take_profit_bps = 0.90;
    double stop_loss_bps = 0.65;
    std::uint64_t max_session_signal_count = 45;
    double session_drawdown_stop_bps = 1.25;
    std::uint64_t min_trades_before_session_stop = 5;
    double min_session_average_trade_bps = 0.10;
    double min_open_window_profile_score = 0.18;
    double max_open_window_signal_flip_ratio = 0.35;
    double round_trip_cost_bps = 0.10;
    bool enable_longs = true;
    bool enable_shorts = false;
    bool open_only = true;
    std::uint64_t open_window_minutes = 60;
};

struct Position
{
    bool active = false;
    SignalState side = SignalState::Neutral;
    double entry_price = 0.0;
    double entry_conviction = 0.0;
    double entry_regime_quality = 0.0;
    double entry_expected_edge_bps = 0.0;
    std::uint64_t entry_sequence = 0;
    std::uint64_t entry_timestamp_ns = 0;
};

struct CompletedTrade
{
    SignalState side = SignalState::Neutral;
    std::uint64_t entry_sequence = 0;
    std::uint64_t exit_sequence = 0;
    std::uint64_t entry_timestamp_ns = 0;
    std::uint64_t exit_timestamp_ns = 0;
    double entry_price = 0.0;
    double exit_price = 0.0;
    double gross_return_bps = 0.0;
    double net_return_bps = 0.0;
    std::uint64_t holding_events = 0;
};

struct StrategyStats
{
    std::uint32_t completed_trades = 0;
    std::uint32_t wins = 0;
    std::uint32_t long_trades = 0;
    std::uint32_t short_trades = 0;
    std::uint32_t long_wins = 0;
    std::uint32_t short_wins = 0;
    double total_net_return_bps = 0.0;
    double average_trade_bps = 0.0;
    double win_rate = 0.0;
    double long_net_return_bps = 0.0;
    double short_net_return_bps = 0.0;
    double long_average_trade_bps = 0.0;
    double short_average_trade_bps = 0.0;
    double long_win_rate = 0.0;
    double short_win_rate = 0.0;
    double max_drawdown_bps = 0.0;
    double sharpe = 0.0;
};

inline double basis_points_return(double entry_price, double exit_price, SignalState side)
{
    if (entry_price <= 0.0 || exit_price <= 0.0 || side == SignalState::Neutral) {
        return 0.0;
    }

    const double raw_return = side == SignalState::LongBias
        ? (exit_price - entry_price) / entry_price
        : (entry_price - exit_price) / entry_price;
    return raw_return * 10000.0;
}

inline double compute_sharpe(const std::vector<double>& returns_bps)
{
    if (returns_bps.size() < 2) {
        return 0.0;
    }

    const double mean =
        std::accumulate(returns_bps.begin(), returns_bps.end(), 0.0) /
        static_cast<double>(returns_bps.size());

    double variance = 0.0;
    for (double value : returns_bps) {
        const double diff = value - mean;
        variance += diff * diff;
    }

    variance /= static_cast<double>(returns_bps.size() - 1);
    const double stddev = std::sqrt(variance);
    if (stddev == 0.0) {
        return 0.0;
    }

    return (mean / stddev) * std::sqrt(static_cast<double>(returns_bps.size()));
}

inline double clamp01(double value)
{
    return std::max(0.0, std::min(1.0, value));
}

class MicrostructureStrategy
{
public:
    explicit MicrostructureStrategy(StrategyConfig config = {})
        : config_(config),
          active_config_(config)
    {
    }

    void set_session_start_timestamp_ns(std::uint64_t timestamp_ns)
    {
        if (timestamp_ns != 0) {
            session_start_timestamp_ns_ = timestamp_ns;
            session_paused_ = false;
            active_config_ = config_;
            active_open_window_minutes_ = active_config_.open_window_minutes;
            window_profile_samples_ = 0;
            window_profile_score_sum_ = 0.0;
            window_profile_score_sq_sum_ = 0.0;
            window_profile_signal_count_ = 0;
            window_profile_signal_flip_count_ = 0;
            window_profile_last_signal_ = SignalState::Neutral;
            window_profile_locked_ = false;
            session_regime_ok_ = true;
            selected_profile_ = SessionProfile::Unknown;
        }
    }

    StrategyOutput evaluate_signal(const FeatureEvent& feature) const
    {
        if (!in_open_window(feature.timestamp_ns)) {
            return {};
        }

        const StrategyConfig& cfg = active_config_;

        const double spread_shock_bps =
            std::max(0.0, feature.spread_bps_100ms - std::max(feature.spread_bps_1s, cfg.min_spread_bps));
        const double imbalance_impulse = feature.imbalance_100ms - feature.imbalance_1s;
        const double microprice_impulse_bps =
            feature.microprice_edge_100ms_bps - feature.microprice_edge_1s_bps;
        const double size_skew =
            (feature.avg_bid_size_1s - feature.avg_ask_size_1s) /
            std::max(feature.avg_bid_size_1s + feature.avg_ask_size_1s, 1e-9);
        const double quote_burst =
            std::max(0.0,
                     (feature.quote_rate_1s - cfg.min_quote_rate_1s) /
                         std::max(cfg.min_quote_rate_1s, 1.0));
        const double spread_regime_ratio =
            feature.spread_bps_100ms / std::max(feature.spread_bps_1s, cfg.min_spread_bps);

        const double directional_score =
            (feature.imbalance_100ms * 0.42) +
            (imbalance_impulse * 0.34) +
            (feature.microprice_edge_100ms_bps * 0.18) +
            (microprice_impulse_bps * 0.20) +
            (size_skew * 0.08);
        const double ignition_intensity =
            (spread_shock_bps * 0.42) +
            (std::abs(imbalance_impulse) * 0.95) +
            (std::abs(microprice_impulse_bps) * 0.34) +
            (quote_burst * 0.70) +
            (std::abs(feature.microprice_edge_100ms_bps) * 0.10);
        const double expected_edge_bps =
            (ignition_intensity * 0.48) +
            (std::abs(feature.microprice_edge_100ms_bps) * 0.26) +
            (feature.spread_bps_100ms * 0.12);
        const double regime_quality =
            (quote_burst * 0.35) +
            ((spread_regime_ratio - 1.0) * 0.45) +
            (std::abs(imbalance_impulse) * 1.05) +
            (std::abs(microprice_impulse_bps) * 0.55) +
            (std::abs(feature.microprice_edge_100ms_bps) * 0.08);
        const double directional_quality =
            (std::abs(directional_score) * 0.80) +
            (std::abs(feature.microprice_edge_100ms_bps) * 0.18) +
            (std::abs(feature.imbalance_100ms) * 0.35);
        const bool long_context_ok =
            feature.imbalance_1s >= -0.03 &&
            feature.microprice_edge_1s_bps >= -0.04;
        const bool short_context_ok =
            feature.imbalance_1s <= 0.03 &&
            feature.microprice_edge_1s_bps <= 0.04;

        const bool spread_ok =
            feature.spread_bps_100ms >= cfg.min_spread_bps &&
            feature.spread_bps_100ms <= cfg.max_spread_bps;
        const bool liquidity_ok = feature.quote_rate_1s >= cfg.min_quote_rate_1s;
        const bool edge_ok =
            expected_edge_bps >= std::max(cfg.min_expected_edge_bps,
                                          cfg.round_trip_cost_bps + (feature.spread_bps_100ms * 0.10));
        const bool ignition_detected =
            ignition_intensity >= cfg.entry_threshold &&
            quote_burst >= 0.10 &&
            spread_regime_ratio >= 1.08 &&
            std::abs(imbalance_impulse) >= 0.12 &&
            std::abs(microprice_impulse_bps) >= 0.08;
        const bool regime_ok =
            regime_quality >= cfg.min_regime_quality &&
            directional_quality >= cfg.min_directional_quality &&
            feature.spread_bps_100ms <= (feature.spread_bps_1s + 1.75);

        StrategyOutput output;
        output.score = directional_score;
        output.conviction =
            std::min(1.0, std::max(std::abs(directional_score), ignition_intensity) / 1.40);
        output.expected_edge_bps = expected_edge_bps;
        output.regime_quality = regime_quality;
        const double normalized_regime_quality = clamp01(regime_quality / 1.50);
        output.size_multiplier =
            0.35 + (0.65 * clamp01((output.conviction * 0.75) + (normalized_regime_quality * 0.25)));

        if (!spread_ok || !liquidity_ok || !edge_ok || !ignition_detected || !regime_ok) {
            return output;
        }

        const bool long_alignment =
            directional_score >= 0.26 &&
            feature.imbalance_100ms >= 0.12 &&
            imbalance_impulse >= 0.12 &&
            microprice_impulse_bps >= 0.08 &&
            feature.microprice_edge_100ms_bps >= 0.05 &&
            long_context_ok;
        const bool short_alignment =
            directional_score <= -0.26 &&
            feature.imbalance_100ms <= -0.12 &&
            imbalance_impulse <= -0.12 &&
            microprice_impulse_bps <= -0.08 &&
            feature.microprice_edge_100ms_bps <= -0.05 &&
            short_context_ok;

        if (cfg.enable_longs && long_alignment) {
            output.signal = SignalState::LongBias;
        } else if (cfg.enable_shorts && short_alignment) {
            output.signal = SignalState::ShortBias;
        }

        update_open_window_profile(feature, output);

        return output;
    }

    void on_feature(const FeatureEvent& feature)
    {
        if (session_start_timestamp_ns_ == 0) {
            session_start_timestamp_ns_ = feature.timestamp_ns;
        }

        const StrategyOutput output = evaluate_signal(feature);

        if (!position_.active) {
            try_open_position(feature, output);
        } else {
            try_close_position(feature, output);
        }

        last_output_ = output;
    }

    const StrategyOutput& last_output() const
    {
        return last_output_;
    }

    const Position& current_position() const
    {
        return position_;
    }

    const std::vector<CompletedTrade>& completed_trades() const
    {
        return completed_trades_;
    }

    std::uint64_t active_open_window_minutes() const
    {
        return active_open_window_minutes_;
    }

    double window_profile_average_score() const
    {
        if (window_profile_samples_ == 0) {
            return 0.0;
        }
        return window_profile_score_sum_ / static_cast<double>(window_profile_samples_);
    }

    double window_profile_score_stddev() const
    {
        if (window_profile_samples_ < 2) {
            return 0.0;
        }

        const double count = static_cast<double>(window_profile_samples_);
        const double mean = window_profile_score_sum_ / count;
        const double mean_square = window_profile_score_sq_sum_ / count;
        const double variance = std::max(0.0, mean_square - (mean * mean));
        return std::sqrt(variance);
    }

    std::uint64_t window_profile_signal_count() const
    {
        return window_profile_signal_count_;
    }

    std::uint64_t window_profile_signal_flip_count() const
    {
        return window_profile_signal_flip_count_;
    }

    StrategyStats stats() const
    {
        StrategyStats stats;
        if (completed_trades_.empty()) {
            return stats;
        }

        std::vector<double> returns_bps;
        double equity_curve = 0.0;
        double peak = 0.0;
        returns_bps.reserve(completed_trades_.size());

        for (const CompletedTrade& trade : completed_trades_) {
            ++stats.completed_trades;
            stats.total_net_return_bps += trade.net_return_bps;
            if (trade.net_return_bps > 0.0) {
                ++stats.wins;
            }
            if (trade.side == SignalState::LongBias) {
                ++stats.long_trades;
                stats.long_net_return_bps += trade.net_return_bps;
                if (trade.net_return_bps > 0.0) {
                    ++stats.long_wins;
                }
            } else if (trade.side == SignalState::ShortBias) {
                ++stats.short_trades;
                stats.short_net_return_bps += trade.net_return_bps;
                if (trade.net_return_bps > 0.0) {
                    ++stats.short_wins;
                }
            }

            equity_curve += trade.net_return_bps;
            peak = std::max(peak, equity_curve);
            stats.max_drawdown_bps = std::max(stats.max_drawdown_bps, peak - equity_curve);
            returns_bps.push_back(trade.net_return_bps);
        }

        stats.average_trade_bps =
            stats.total_net_return_bps / static_cast<double>(completed_trades_.size());
        stats.win_rate =
            static_cast<double>(stats.wins) / static_cast<double>(completed_trades_.size());
        if (stats.long_trades > 0) {
            stats.long_average_trade_bps =
                stats.long_net_return_bps / static_cast<double>(stats.long_trades);
            stats.long_win_rate =
                static_cast<double>(stats.long_wins) / static_cast<double>(stats.long_trades);
        }
        if (stats.short_trades > 0) {
            stats.short_average_trade_bps =
                stats.short_net_return_bps / static_cast<double>(stats.short_trades);
            stats.short_win_rate =
                static_cast<double>(stats.short_wins) / static_cast<double>(stats.short_trades);
        }
        stats.sharpe = compute_sharpe(returns_bps);
        return stats;
    }

private:
    void apply_session_profile(SessionProfile profile) const
    {
        active_config_ = config_;
        switch (profile) {
            case SessionProfile::Strong:
                active_config_.entry_threshold = 1.30;
                active_config_.min_spread_bps = 0.06;
                active_config_.min_quote_rate_1s = 34.0;
                active_config_.min_expected_edge_bps = 0.24;
                active_config_.min_regime_quality = 0.85;
                active_config_.min_directional_quality = 0.22;
                active_config_.max_hold_events = 16;
                active_config_.take_profit_bps = 1.00;
                active_config_.stop_loss_bps = 0.55;
                active_config_.open_window_minutes = 60;
                break;
            case SessionProfile::Base:
                active_config_.entry_threshold = 1.10;
                active_config_.min_spread_bps = 0.10;
                active_config_.min_quote_rate_1s = 28.0;
                active_config_.min_expected_edge_bps = 0.24;
                active_config_.min_regime_quality = 0.85;
                active_config_.min_directional_quality = 0.22;
                active_config_.max_hold_events = 12;
                active_config_.take_profit_bps = 0.90;
                active_config_.stop_loss_bps = 0.65;
                active_config_.open_window_minutes = 60;
                break;
            case SessionProfile::Skip:
            case SessionProfile::Unknown:
            default:
                break;
        }
    }

    void update_open_window_profile(const FeatureEvent& feature, const StrategyOutput& output) const
    {
        const StrategyConfig& cfg = active_config_;

        if (!cfg.open_only || session_start_timestamp_ns_ == 0 || window_profile_locked_) {
            return;
        }

        const std::uint64_t warmup_ns = 2ULL * 60ULL * 1000000000ULL;
        const std::uint64_t elapsed_ns =
            feature.timestamp_ns > session_start_timestamp_ns_
                ? (feature.timestamp_ns - session_start_timestamp_ns_)
                : 0ULL;

        const double spread_shock_bps =
            std::max(0.0, feature.spread_bps_100ms - std::max(feature.spread_bps_1s, cfg.min_spread_bps));
        const double imbalance_impulse = feature.imbalance_100ms - feature.imbalance_1s;
        const double microprice_impulse_bps =
            feature.microprice_edge_100ms_bps - feature.microprice_edge_1s_bps;
        const double size_skew =
            (feature.avg_bid_size_1s - feature.avg_ask_size_1s) /
            std::max(feature.avg_bid_size_1s + feature.avg_ask_size_1s, 1e-9);
        const double quote_burst =
            std::max(0.0,
                     (feature.quote_rate_1s - cfg.min_quote_rate_1s) /
                         std::max(cfg.min_quote_rate_1s, 1.0));

        const double burst_score =
            (clamp01(quote_burst / 0.40) * 0.30) +
            (clamp01(spread_shock_bps / 0.25) * 0.20) +
            (clamp01(std::abs(imbalance_impulse) / 0.18) * 0.20) +
            (clamp01(std::abs(microprice_impulse_bps) / 0.12) * 0.20) +
            (clamp01(std::abs(size_skew) / 0.20) * 0.10);

        ++window_profile_samples_;
        window_profile_score_sum_ += burst_score;
        window_profile_score_sq_sum_ += burst_score * burst_score;
        if (output.signal != SignalState::Neutral) {
            ++window_profile_signal_count_;
            if (window_profile_last_signal_ != SignalState::Neutral &&
                window_profile_last_signal_ != output.signal) {
                ++window_profile_signal_flip_count_;
            }
            window_profile_last_signal_ = output.signal;
        }

        if (elapsed_ns < warmup_ns) {
            return;
        }

        if (window_profile_signal_count_ >= cfg.max_session_signal_count) {
            session_paused_ = true;
        }

        const double average_profile_score = window_profile_average_score();
        const double profile_score_stddev = window_profile_score_stddev();
        const double signal_flip_ratio = window_profile_signal_count_ > 0
            ? static_cast<double>(window_profile_signal_flip_count_) /
                  static_cast<double>(window_profile_signal_count_)
            : 0.0;
        if (average_profile_score >= 0.30 && signal_flip_ratio <= 0.18) {
            selected_profile_ = SessionProfile::Strong;
            apply_session_profile(selected_profile_);
            session_regime_ok_ = true;
        } else if (average_profile_score >= 0.20 && signal_flip_ratio <= 0.30) {
            selected_profile_ = SessionProfile::Base;
            apply_session_profile(selected_profile_);
            session_regime_ok_ = true;
        } else {
            selected_profile_ = SessionProfile::Skip;
            session_regime_ok_ = false;
            session_paused_ = true;
        }

        active_open_window_minutes_ = active_config_.open_window_minutes;

        window_profile_locked_ = true;
    }

    bool in_open_window(std::uint64_t timestamp_ns) const
    {
        if (!active_config_.open_only || session_start_timestamp_ns_ == 0) {
            return true;
        }

        const std::uint64_t window_ns =
            active_open_window_minutes_ * 60ULL * 1000000000ULL;
        return timestamp_ns - session_start_timestamp_ns_ <= window_ns;
    }

    void try_open_position(const FeatureEvent& feature, const StrategyOutput& output)
    {
        if (session_paused_ || !session_regime_ok_ ||
            (active_config_.open_only && !window_profile_locked_) ||
            output.signal == SignalState::Neutral) {
            return;
        }

        position_.active = true;
        position_.side = output.signal;
        position_.entry_price = output.signal == SignalState::LongBias
            ? feature.ask_price
            : feature.bid_price;
        position_.entry_conviction = output.conviction;
        position_.entry_regime_quality = output.regime_quality;
        position_.entry_expected_edge_bps = output.expected_edge_bps;
        position_.entry_sequence = feature.sequence;
        position_.entry_timestamp_ns = feature.timestamp_ns;
    }

    void try_close_position(const FeatureEvent& feature, const StrategyOutput& output)
    {
        const StrategyConfig& cfg = active_config_;
        const std::uint64_t held_events = feature.sequence - position_.entry_sequence;
        const double entry_conviction = clamp01(position_.entry_conviction);
        const double entry_regime_quality = clamp01(position_.entry_regime_quality / 1.50);
        const double dynamic_exit_threshold =
            cfg.exit_threshold +
            (0.10 * (1.0 - entry_conviction)) +
            (0.05 * std::max(0.0, 0.88 - entry_regime_quality));
        const double dynamic_take_profit_bps =
            cfg.take_profit_bps * (0.90 + (0.18 * entry_conviction));
        const double dynamic_stop_loss_bps =
            cfg.stop_loss_bps * (0.85 + (0.20 * entry_conviction));
        const std::uint64_t dynamic_max_hold_events =
            cfg.max_hold_events +
            static_cast<std::uint64_t>(std::llround(entry_conviction * 3.0));
        const double exit_price = position_.side == SignalState::LongBias
            ? feature.bid_price
            : feature.ask_price;
        const double current_gross_return_bps =
            basis_points_return(position_.entry_price, exit_price, position_.side);

        bool should_exit = false;
        if (position_.side == SignalState::LongBias) {
            should_exit =
                output.score < dynamic_exit_threshold ||
                feature.imbalance_100ms < -0.06 ||
                feature.microprice_edge_100ms_bps < -0.05 ||
                output.expected_edge_bps < (std::max(cfg.min_expected_edge_bps,
                                                      position_.entry_expected_edge_bps * 0.70));
        } else if (position_.side == SignalState::ShortBias) {
            should_exit =
                output.score > -dynamic_exit_threshold ||
                feature.imbalance_100ms > 0.06 ||
                feature.microprice_edge_100ms_bps > 0.05 ||
                output.expected_edge_bps < (std::max(cfg.min_expected_edge_bps,
                                                      position_.entry_expected_edge_bps * 0.70));
        }

        if (output.signal != SignalState::Neutral && output.signal != position_.side) {
            should_exit = true;
        }

        if (current_gross_return_bps >= dynamic_take_profit_bps ||
            current_gross_return_bps <= -dynamic_stop_loss_bps ||
            held_events >= dynamic_max_hold_events) {
            should_exit = true;
        }

        if (!should_exit) {
            return;
        }

        CompletedTrade trade;
        trade.side = position_.side;
        trade.entry_sequence = position_.entry_sequence;
        trade.exit_sequence = feature.sequence;
        trade.entry_timestamp_ns = position_.entry_timestamp_ns;
        trade.exit_timestamp_ns = feature.timestamp_ns;
        trade.entry_price = position_.entry_price;
        trade.exit_price = exit_price;
        trade.gross_return_bps =
            basis_points_return(trade.entry_price, trade.exit_price, trade.side);
        trade.net_return_bps = trade.gross_return_bps - cfg.round_trip_cost_bps;
        trade.holding_events = held_events;

        completed_trades_.push_back(trade);
        ++session_closed_trades_;
        session_equity_bps_ += trade.net_return_bps;
        session_peak_equity_bps_ = std::max(session_peak_equity_bps_, session_equity_bps_);
        if (trade.net_return_bps > 0.0) {
            session_consecutive_losses_ = 0;
        } else {
            ++session_consecutive_losses_;
        }
        const double session_average_trade_bps =
            session_equity_bps_ / static_cast<double>(session_closed_trades_);
        const double session_drawdown_bps = session_peak_equity_bps_ - session_equity_bps_;
        if (session_closed_trades_ >= active_config_.min_trades_before_session_stop &&
            (session_equity_bps_ <= 0.0 ||
             session_consecutive_losses_ >= 2 ||
             session_drawdown_bps >= active_config_.session_drawdown_stop_bps ||
             session_average_trade_bps < active_config_.min_session_average_trade_bps)) {
            session_paused_ = true;
        }
        position_ = Position{};
    }

    StrategyConfig config_{}; 
    mutable StrategyConfig active_config_{};
    mutable std::uint64_t session_start_timestamp_ns_ = 0;
    mutable std::uint64_t active_open_window_minutes_ = 60;
    mutable std::uint64_t window_profile_samples_ = 0;
    mutable double window_profile_score_sum_ = 0.0;
    mutable double window_profile_score_sq_sum_ = 0.0;
    mutable std::uint64_t window_profile_signal_count_ = 0;
    mutable std::uint64_t window_profile_signal_flip_count_ = 0;
    mutable SignalState window_profile_last_signal_ = SignalState::Neutral;
    mutable bool window_profile_locked_ = false;
    mutable bool session_regime_ok_ = true;
    mutable SessionProfile selected_profile_ = SessionProfile::Unknown;
    Position position_{};
    StrategyOutput last_output_{};
    std::vector<CompletedTrade> completed_trades_{};
    double session_equity_bps_ = 0.0;
    double session_peak_equity_bps_ = 0.0;
    std::uint64_t session_closed_trades_ = 0;
    std::uint64_t session_consecutive_losses_ = 0;
    mutable bool session_paused_ = false;
};

inline const char* signal_to_string(SignalState signal)
{
    switch (signal) {
        case SignalState::LongBias:
            return "LONG_BIAS";
        case SignalState::ShortBias:
            return "SHORT_BIAS";
        default:
            return "NEUTRAL";
    }
}

} // namespace momentum

