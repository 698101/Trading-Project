#include <algorithm>
#include <array>
#include <cmath>
#include <deque>
#include <cstdint>
#include <cstring>
#include <cctype>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <limits>
#include <numeric>
#include <optional>
#include <random>
#include <sstream>
#include <stdexcept>
#include <string>
#include <vector>


#include "risk_and_execution.cpp"
#include "strategies.cpp"


namespace
{
struct RawQuote
{
    std::uint64_t timestamp_ns = 0;
    std::string symbol;
    double bid_price = 0.0;
    double ask_price = 0.0;
    double bid_size = 0.0;
    double ask_size = 0.0;
};

struct PortfolioConfig
{
    std::size_t rolling_window = 75;
    double min_edge_bps = 0.20;
    double forecast_weight = 0.70;
    double min_ml_win_probability = 0.52;
    double max_gross_exposure = 1.0;
    std::uint64_t min_reentry_events = 40;
    std::uint64_t interval_ns = 60ULL * 1000000000ULL;
    std::uint64_t seed = 1337;
    std::string forecast_mode = "heuristic";
    std::string portfolio_mode = "full";
    std::string decision_mode = "off";
    std::string ml_model_path;
    std::string output_prefix;
    std::string trade_log_path;
    std::string rejected_signals_path;
    double adverse_selection_bps = 0.0;
    std::uint64_t signal_latency_us = 0;
    double mm_min_entry_microprice_edge_100ms_bps = 0.0;
    double mm_min_entry_spread_100ms_bps = 0.0;
    double mm_max_entry_side_imbalance_1s = 1.0;
};

constexpr std::size_t kFeatureCount = 13;

const std::array<std::string, kFeatureCount>& feature_names()
{
    static const std::array<std::string, kFeatureCount> names = {
        "spread_bps_1s",
        "spread_bps_100ms",
        "side_imbalance_100ms",
        "side_imbalance_1s",
        "side_microprice_edge_100ms_bps",
        "side_microprice_edge_1s_bps",
        "quote_rate_1s_scaled",
        "avg_bid_size_1s_scaled",
        "avg_ask_size_1s_scaled",
        "regime_quality",
        "conviction",
        "abs_score",
        "signal_expected_edge_bps",
    };
    return names;
}

struct EntryFeatureVector
{
    std::array<double, kFeatureCount> values{};
};

struct MlPrediction
{
    double expected_edge_bps = 0.0;
    double win_probability = 0.50;
    bool used_ml = false;
};

std::vector<std::string> split_csv_line(const std::string& line)
{
    std::vector<std::string> columns;
    std::stringstream stream(line);
    std::string token;
    while (std::getline(stream, token, ',')) {
        columns.push_back(token);
    }
    return columns;
}

double logistic(double value)
{
    if (value >= 35.0) {
        return 1.0;
    }
    if (value <= -35.0) {
        return 0.0;
    }
    return 1.0 / (1.0 + std::exp(-value));
}

struct MlSleeveModel
{
    bool enabled = false;
    double linear_intercept = 0.0;
    double logistic_intercept = 0.0;
    std::array<double, kFeatureCount> linear_coefficients{};
    std::array<double, kFeatureCount> logistic_coefficients{};

    double linear_edge(const EntryFeatureVector& features) const
    {
        double value = linear_intercept;
        for (std::size_t i = 0; i < kFeatureCount; ++i) {
            value += linear_coefficients[i] * features.values[i];
        }
        return std::isfinite(value) ? value : 0.0;
    }

    double win_probability(const EntryFeatureVector& features) const
    {
        double value = logistic_intercept;
        for (std::size_t i = 0; i < kFeatureCount; ++i) {
            value += logistic_coefficients[i] * features.values[i];
        }
        return logistic(value);
    }
};

struct MlModel
{
    std::array<MlSleeveModel, 3> sleeves{};

    bool any_enabled() const
    {
        return sleeves[0].enabled || sleeves[1].enabled || sleeves[2].enabled;
    }

    void load(const std::string& path)
    {
        std::ifstream input(path);
        if (!input) {
            throw std::runtime_error("Could not open ML model: " + path);
        }

        std::string line;
        std::getline(input, line);
        while (std::getline(input, line)) {
            if (line.empty()) {
                continue;
            }
            const std::vector<std::string> columns = split_csv_line(line);
            const std::size_t expected_columns = 3 + (kFeatureCount * 2);
            if (columns.size() < expected_columns) {
                continue;
            }

            const int sleeve = std::stoi(columns[0]);
            if (sleeve < 0 || sleeve >= static_cast<int>(sleeves.size())) {
                continue;
            }

            MlSleeveModel model;
            model.enabled = true;
            model.linear_intercept = std::stod(columns[1]);
            for (std::size_t i = 0; i < kFeatureCount; ++i) {
                model.linear_coefficients[i] = std::stod(columns[2 + i]);
            }
            const std::size_t logistic_offset = 2 + kFeatureCount;
            model.logistic_intercept = std::stod(columns[logistic_offset]);
            for (std::size_t i = 0; i < kFeatureCount; ++i) {
                model.logistic_coefficients[i] = std::stod(columns[logistic_offset + 1 + i]);
            }
            sleeves[static_cast<std::size_t>(sleeve)] = model;
        }

        if (!any_enabled()) {
            throw std::runtime_error("ML model contained no usable sleeve coefficients: " + path);
        }
    }

    MlPrediction predict(std::size_t sleeve_id,
                         const EntryFeatureVector& features,
                         double fallback_edge_bps) const
    {
        if (sleeve_id >= sleeves.size() || !sleeves[sleeve_id].enabled) {
            return {fallback_edge_bps, 0.50, false};
        }

        const MlSleeveModel& model = sleeves[sleeve_id];
        return {
            model.linear_edge(features),
            model.win_probability(features),
            true,
        };
    }
};

struct RollingEdgeVariance
{
    explicit RollingEdgeVariance(std::size_t max_count = 75)
        : max_count(max_count)
    {
    }

    void add(double net_return_bps)
    {
        if (returns.size() == max_count) {
            returns.erase(returns.begin());
        }
        returns.push_back(net_return_bps);
    }

    hft::portfolio::StrategyForecast forecast(double signal_expected_edge_bps) const
    {
        const std::size_t min_history =
            std::min<std::size_t>(50, std::max<std::size_t>(8, max_count / 2));
        if (returns.size() < min_history) {
            return {signal_expected_edge_bps, 1.0};
        }

        const double mean =
            std::accumulate(returns.begin(), returns.end(), 0.0) /
            static_cast<double>(returns.size());

        double variance = 0.0;
        for (double value : returns) {
            const double diff = value - mean;
            variance += diff * diff;
        }
        variance /= static_cast<double>(returns.size() - 1);
        const double blended_edge_bps = (mean * 0.65) + (signal_expected_edge_bps * 0.35);
        return {blended_edge_bps, std::max(variance, 1e-6)};
    }

    std::size_t max_count = 75;
    std::vector<double> returns;
};

struct OpenPosition
{
    bool active = false;
    int side = 0;
    double entry_price = 0.0;
    double entry_expected_edge_bps = 0.0;
    double entry_signal_expected_edge_bps = 0.0;
    double entry_ml_win_probability = 0.50;
    double entry_score = 0.0;
    double entry_conviction = 0.0;
    double entry_mid_price = 0.0;
    double entry_spread_bps = 0.0;
    double weight = 0.0;
    std::uint64_t entry_sequence = 0;
    std::uint64_t entry_timestamp_ns = 0;
    std::array<double, kFeatureCount> entry_features{};
};

struct SleeveState
{
    std::string name;
    RollingEdgeVariance edge_model;
    OpenPosition position;
    std::uint32_t completed_trades = 0;
    std::uint32_t skipped_low_edge = 0;
    std::uint64_t last_exit_sequence = 0;
    double total_net_return_bps = 0.0;
    double missed_expected_edge_bps = 0.0;
};

struct PortfolioStats
{
    std::uint64_t processed_quotes = 0;
    std::uint32_t completed_trades = 0;
    std::uint32_t winning_trades = 0;
    std::uint32_t skipped_low_edge = 0;
    std::uint32_t latency_expired_signals = 0;
    double total_net_return_bps = 0.0;
    double max_drawdown_bps = 0.0;
    double sharpe = 0.0;
    double trade_sharpe = 0.0;
    double trade_win_rate = 0.0;
    double missed_expected_edge_bps = 0.0;
    std::uint32_t return_intervals = 0;
};

struct IntervalPoint
{
    std::uint64_t interval_id = 0;
    std::uint64_t timestamp_ns = 0;
    double return_bps = 0.0;
    double equity_bps = 0.0;
    double drawdown_bps = 0.0;
};

struct DelayedFeatureFrame
{
    mm::FeatureEvent mm_feature{};
    liquidity::FeatureEvent liquidity_feature{};
    momentum::FeatureEvent momentum_feature{};
};

template <typename QuoteT>
void copy_quote(const RawQuote& source, QuoteT& target, std::uint64_t sequence)
{
    target.sequence = sequence;
    target.source_timestamp_ns = source.timestamp_ns;
    target.parsed_timestamp_ns = source.timestamp_ns;
    target.bid_price = source.bid_price;
    target.ask_price = source.ask_price;
    target.bid_size = source.bid_size;
    target.ask_size = source.ask_size;
    target.symbol.fill('\0');
    const std::size_t count = std::min(target.symbol.size() - 1, source.symbol.size());
    std::memcpy(target.symbol.data(), source.symbol.data(), count);
}

std::optional<RawQuote> parse_quote_line(const std::string& line)
{
    if (line.empty() || line.find("timestamp_ns") != std::string::npos) {
        return std::nullopt;
    }

    std::stringstream stream(line);
    std::string timestamp_token;
    std::string symbol_token;
    std::string bid_price_token;
    std::string ask_price_token;
    std::string bid_size_token;
    std::string ask_size_token;

    if (!std::getline(stream, timestamp_token, ',')) return std::nullopt;
    if (!std::getline(stream, symbol_token, ',')) return std::nullopt;
    if (!std::getline(stream, bid_price_token, ',')) return std::nullopt;
    if (!std::getline(stream, ask_price_token, ',')) return std::nullopt;
    if (!std::getline(stream, bid_size_token, ',')) return std::nullopt;
    if (!std::getline(stream, ask_size_token, ',')) return std::nullopt;

    try {
        RawQuote quote;
        quote.timestamp_ns = std::stoull(timestamp_token);
        quote.symbol = symbol_token;
        quote.bid_price = std::stod(bid_price_token);
        quote.ask_price = std::stod(ask_price_token);
        quote.bid_size = std::stod(bid_size_token);
        quote.ask_size = std::stod(ask_size_token);
        if (quote.bid_price <= 0.0 || quote.ask_price <= quote.bid_price) {
            return std::nullopt;
        }
        return quote;
    } catch (...) {
        return std::nullopt;
    }
}

double compute_sharpe(const std::vector<double>& returns_bps)
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

double compute_return_quality(const std::vector<double>& returns_bps)
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
    return stddev == 0.0 ? 0.0 : mean / stddev;
}

double basis_points_return(double entry_price, double exit_price, int side)
{
    if (entry_price <= 0.0 || exit_price <= 0.0 || side == 0) {
        return 0.0;
    }
    const double raw_return = side > 0
        ? (exit_price - entry_price) / entry_price
        : (entry_price - exit_price) / entry_price;
    return raw_return * 10000.0;
}

void flush_return_intervals(std::vector<double>& interval_returns_bps,
                            std::vector<IntervalPoint>& interval_points,
                            std::uint64_t& current_interval,
                            double& current_interval_return_bps,
                            double equity_bps,
                            double peak_bps,
                            std::uint64_t timestamp_ns,
                            std::uint64_t interval_ns)
{
    const std::uint64_t next_interval = timestamp_ns / interval_ns;
    while (current_interval < next_interval) {
        interval_returns_bps.push_back(current_interval_return_bps);
        interval_points.push_back({
            current_interval,
            current_interval * interval_ns,
            current_interval_return_bps,
            equity_bps,
            -(peak_bps - equity_bps),
        });
        current_interval_return_bps = 0.0;
        ++current_interval;
    }
}

double active_capital(const std::array<SleeveState, 3>& sleeves)
{
    double total = 0.0;
    for (const SleeveState& sleeve : sleeves) {
        if (sleeve.position.active) {
            total += sleeve.position.weight;
        }
    }
    return total;
}

template <typename FeatureT, typename OutputT>
double conservative_entry_fill_probability(const FeatureT& feature,
                                           const OutputT& output,
                                           int side,
                                           bool passive_execution)
{
    const bool bid_side = side > 0;
    const double displayed_size = bid_side ? feature.bid_size : feature.ask_size;
    const double opposite_size = bid_side ? feature.ask_size : feature.bid_size;
    const double queue_factor = 1.0 / (1.0 + (displayed_size / 160.0));
    const double opposite_pressure =
        hft::portfolio::clamp01(opposite_size / std::max(displayed_size + opposite_size, 1.0));
    const double spread_factor = hft::portfolio::clamp01((feature.spread_bps_1s - 0.06) / 2.50);
    const double conviction_factor = 0.35 + (output.conviction * 0.55);
    const double edge_factor = 0.40 + (hft::portfolio::clamp01(output.expected_edge_bps / 1.50) * 0.45);
    const double base = passive_execution ? 0.008 : 0.018;
    const double cap = passive_execution ? 0.08 : 0.16;
    return std::min(cap,
                    (base + (spread_factor * 0.10) + (opposite_pressure * 0.08)) *
                    queue_factor * conviction_factor * edge_factor);
}

double sampled_partial_fill_fraction(std::mt19937_64& rng, double fill_probability)
{
    std::uniform_real_distribution<double> uniform(0.0, 1.0);
    const double fill_quality = hft::portfolio::clamp01(fill_probability / 0.16);
    return 0.25 + (uniform(rng) * 0.45) + (fill_quality * 0.30);
}

template <typename SignalStateT>
int side_to_int(SignalStateT side)
{
    return static_cast<int>(side);
}

const char* side_to_label(int side)
{
    if (side > 0) {
        return "long";
    }
    if (side < 0) {
        return "short";
    }
    return "flat";
}

template <typename FeatureT>
double passive_entry_price(const FeatureT& feature, int side)
{
    return side > 0 ? feature.bid_price : feature.ask_price;
}

template <typename FeatureT>
double passive_exit_price(const FeatureT& feature, int side)
{
    return side > 0 ? feature.ask_price : feature.bid_price;
}

template <typename FeatureT>
double aggressive_entry_price(const FeatureT& feature, int side)
{
    return side > 0 ? feature.ask_price : feature.bid_price;
}

template <typename FeatureT>
double aggressive_exit_price(const FeatureT& feature, int side)
{
    return side > 0 ? feature.bid_price : feature.ask_price;
}

template <typename OutputT>
double output_regime_quality(const OutputT&)
{
    return 0.0;
}

double output_regime_quality(const liquidity::StrategyOutput& output)
{
    return output.regime_quality;
}

double output_regime_quality(const momentum::StrategyOutput& output)
{
    return output.regime_quality;
}

template <typename FeatureT, typename OutputT>
EntryFeatureVector build_entry_feature_vector(const FeatureT& feature,
                                              const OutputT& output,
                                              int side)
{
    const double signed_side = side >= 0 ? 1.0 : -1.0;
    return {{
        feature.spread_bps_1s,
        feature.spread_bps_100ms,
        signed_side * feature.imbalance_100ms,
        signed_side * feature.imbalance_1s,
        signed_side * feature.microprice_edge_100ms_bps,
        signed_side * feature.microprice_edge_1s_bps,
        feature.quote_rate_1s / 100.0,
        feature.avg_bid_size_1s / 1000.0,
        feature.avg_ask_size_1s / 1000.0,
        output_regime_quality(output),
        output.conviction,
        std::abs(output.score),
        output.expected_edge_bps,
    }};
}

template <typename FeatureT, typename OutputT>
MlPrediction build_edge_prediction(const SleeveState& sleeve,
                                   const FeatureT& feature,
                                   const OutputT& output,
                                   std::size_t sleeve_id,
                                   const PortfolioConfig& config,
                                   const MlModel& ml_model)
{
    const hft::portfolio::StrategyForecast rolling =
        sleeve.edge_model.forecast(output.expected_edge_bps);
    const int side = side_to_int(output.signal);
    if (config.forecast_mode != "ml" || side == 0) {
        return {rolling.expected_edge_bps, 0.50, false};
    }

    const EntryFeatureVector features = build_entry_feature_vector(feature, output, side);
    return ml_model.predict(sleeve_id, features, rolling.expected_edge_bps);
}

template <typename FeatureT, typename OutputT>
std::string position_exit_reason(const OpenPosition& position,
                                 const FeatureT& feature,
                                 const OutputT& output,
                                 bool passive_execution,
                                 double take_profit_bps,
                                 double stop_loss_bps,
                                 std::uint64_t max_hold_events)
{
    const double exit_price = passive_execution
        ? passive_exit_price(feature, position.side)
        : aggressive_exit_price(feature, position.side);
    const double current_return_bps =
        basis_points_return(position.entry_price, exit_price, position.side);
    const int output_side = side_to_int(output.signal);

    if (output_side != 0 && output_side != position.side) {
        return "opposite_signal";
    }
    if (current_return_bps >= take_profit_bps) {
        return "take_profit";
    }
    if (current_return_bps <= -stop_loss_bps) {
        return "stop_loss";
    }
    if (feature.sequence - position.entry_sequence >= max_hold_events) {
        return "max_hold_events";
    }
    return "";
}

template <typename FeatureT>
double close_position(SleeveState& sleeve,
                      const FeatureT& feature,
                      std::size_t sleeve_id,
                      bool passive_execution,
                      double round_trip_cost_bps,
                      double adverse_selection_bps,
                      const std::string& exit_reason,
                      std::ofstream* trade_export)
{
    const double exit_price = passive_execution
        ? passive_exit_price(feature, sleeve.position.side)
        : aggressive_exit_price(feature, sleeve.position.side);
    const double execution_haircut_bps = passive_execution
        ? ((feature.spread_bps_1s * 0.80) + (0.22 * (1.0 - sleeve.position.entry_conviction)) + 0.18)
        : ((feature.spread_bps_1s * 0.25) + 0.12);
    const double gross_return_bps =
        basis_points_return(sleeve.position.entry_price, exit_price, sleeve.position.side);
    const double net_return_bps =
        gross_return_bps -
        round_trip_cost_bps -
        execution_haircut_bps -
        adverse_selection_bps;
    sleeve.edge_model.add(net_return_bps);
    sleeve.total_net_return_bps += net_return_bps;
    ++sleeve.completed_trades;
    sleeve.last_exit_sequence = feature.sequence;
    const double weighted_return_bps = net_return_bps * sleeve.position.weight;
    if (trade_export != nullptr && *trade_export) {
        *trade_export << sleeve.position.entry_timestamp_ns << ","
                      << feature.timestamp_ns << ","
                      << sleeve.position.entry_sequence << ","
                      << feature.sequence << ","
                      << sleeve_id << ","
                      << sleeve.name << ","
                      << side_to_label(sleeve.position.side) << ","
                      << "signal_entry" << ","
                      << exit_reason << ","
                      << (passive_execution ? "passive" : "aggressive") << ","
                      << sleeve.position.weight << ","
                      << sleeve.position.entry_expected_edge_bps << ","
                      << sleeve.position.entry_signal_expected_edge_bps << ","
                      << sleeve.position.entry_ml_win_probability << ","
                      << sleeve.position.entry_score << ","
                      << sleeve.position.entry_conviction << ","
                      << sleeve.position.entry_price << ","
                      << exit_price << ","
                      << sleeve.position.entry_mid_price << ","
                      << feature.mid_price << ","
                      << sleeve.position.entry_spread_bps << ","
                      << feature.spread_bps_1s << ","
                      << gross_return_bps << ","
                      << round_trip_cost_bps << ","
                      << execution_haircut_bps << ","
                      << adverse_selection_bps << ","
                      << net_return_bps << ","
                      << weighted_return_bps << ","
                      << 0.0;
        for (double value : sleeve.position.entry_features) {
            *trade_export << "," << value;
        }
        *trade_export << "\n";
    }
    sleeve.position = {};
    return weighted_return_bps;
}

template <typename FeatureT, typename OutputT>
void write_rejected_signal(std::ofstream* rejected_export,
                           const FeatureT& feature,
                           const OutputT& output,
                           std::size_t sleeve_id,
                           const std::string& sleeve_name,
                           const std::string& reason,
                           const MlPrediction& prediction,
                           double effective_min_edge_bps,
                           double target_weight,
                           double fill_probability)
{
    if (rejected_export == nullptr || !*rejected_export) {
        return;
    }
    *rejected_export << feature.timestamp_ns << ","
                     << feature.sequence << ","
                     << sleeve_id << ","
                     << sleeve_name << ","
                     << side_to_label(side_to_int(output.signal)) << ","
                     << reason << ","
                     << prediction.expected_edge_bps << ","
                     << output.expected_edge_bps << ","
                     << effective_min_edge_bps << ","
                     << output.score << ","
                     << output.conviction << ","
                     << feature.spread_bps_1s << ","
                     << feature.spread_bps_100ms << ","
                     << feature.microprice_edge_100ms_bps << ","
                     << feature.microprice_edge_1s_bps << ","
                     << feature.quote_rate_1s << ","
                     << target_weight << ","
                     << fill_probability << "\n";
}

template <typename FeatureT>
bool market_making_entry_quality_passes(const FeatureT& feature,
                                        int side,
                                        const PortfolioConfig& config)
{
    const double signed_side = side >= 0 ? 1.0 : -1.0;
    const double signed_microprice_edge_100ms_bps =
        signed_side * feature.microprice_edge_100ms_bps;
    const double signed_imbalance_1s = signed_side * feature.imbalance_1s;

    if (signed_microprice_edge_100ms_bps <
        config.mm_min_entry_microprice_edge_100ms_bps) {
        return false;
    }
    if (feature.spread_bps_100ms < config.mm_min_entry_spread_100ms_bps) {
        return false;
    }
    if (signed_imbalance_1s > config.mm_max_entry_side_imbalance_1s) {
        return false;
    }
    return true;
}

template <typename FeatureT, typename OutputT>
void maybe_open_position(SleeveState& sleeve,
                         const FeatureT& feature,
                         const OutputT& output,
                         const hft::portfolio::StrategyWeights& weights,
                         double target_weight,
                         std::size_t sleeve_id,
                         const MlPrediction& prediction,
                         bool passive_execution,
                         const PortfolioConfig& config,
                         double effective_min_edge_bps,
                         double decision_size_multiplier,
                         std::array<SleeveState, 3>& all_sleeves,
                         std::mt19937_64& rng,
                         std::ofstream* rejected_export)
{
    const int side = side_to_int(output.signal);
    if (side == 0 || sleeve.position.active || target_weight <= 0.0) {
        return;
    }
    if (sleeve.last_exit_sequence != 0 &&
        feature.sequence - sleeve.last_exit_sequence < config.min_reentry_events) {
        write_rejected_signal(rejected_export, feature, output, sleeve_id, sleeve.name,
                              "reentry_cooldown", prediction, effective_min_edge_bps,
                              target_weight, 0.0);
        return;
    }

    if (sleeve_id == 0 &&
        !market_making_entry_quality_passes(feature, side, config)) {
        write_rejected_signal(rejected_export, feature, output, sleeve_id, sleeve.name,
                              "mm_entry_quality_filter", prediction,
                              effective_min_edge_bps, target_weight, 0.0);
        return;
    }

    const double expected_edge_bps = prediction.expected_edge_bps;
    const bool raw_signal_too_weak =
        config.forecast_mode != "ml" && output.expected_edge_bps < effective_min_edge_bps;
    const bool ml_probability_too_low =
        prediction.used_ml && prediction.win_probability < config.min_ml_win_probability;
    if (expected_edge_bps < effective_min_edge_bps ||
        raw_signal_too_weak ||
        ml_probability_too_low) {
        ++sleeve.skipped_low_edge;
        sleeve.missed_expected_edge_bps += std::max(0.0, expected_edge_bps) * target_weight;
        const std::string reason = ml_probability_too_low
            ? "ml_probability_below_threshold"
            : (raw_signal_too_weak ? "raw_signal_edge_below_threshold"
                                   : "forecast_edge_below_threshold");
        write_rejected_signal(rejected_export, feature, output, sleeve_id, sleeve.name,
                              reason, prediction, effective_min_edge_bps,
                              target_weight, 0.0);
        return;
    }

    const double fill_probability =
        conservative_entry_fill_probability(feature, output, side, passive_execution);
    std::uniform_real_distribution<double> uniform(0.0, 1.0);
    if (uniform(rng) >= fill_probability) {
        write_rejected_signal(rejected_export, feature, output, sleeve_id, sleeve.name,
                              "entry_fill_not_sampled", prediction, effective_min_edge_bps,
                              target_weight, fill_probability);
        return;
    }

    (void)weights;
    const double free_capital =
        std::max(0.0, config.max_gross_exposure - active_capital(all_sleeves));
    const double ml_size_multiplier = prediction.used_ml
        ? std::clamp(0.60 + prediction.win_probability, 0.50, 1.25)
        : 1.0;
    const double entry_weight =
        std::min(target_weight * ml_size_multiplier * decision_size_multiplier *
                     sampled_partial_fill_fraction(rng, fill_probability),
                 free_capital);
    if (entry_weight <= 0.01) {
        write_rejected_signal(rejected_export, feature, output, sleeve_id, sleeve.name,
                              "insufficient_free_capital", prediction, effective_min_edge_bps,
                              target_weight, fill_probability);
        return;
    }

    sleeve.position.active = true;
    sleeve.position.side = side;
    sleeve.position.entry_price = passive_execution
        ? passive_entry_price(feature, side)
        : aggressive_entry_price(feature, side);
    sleeve.position.entry_expected_edge_bps = expected_edge_bps;
    sleeve.position.entry_signal_expected_edge_bps = output.expected_edge_bps;
    sleeve.position.entry_ml_win_probability = prediction.win_probability;
    sleeve.position.entry_score = output.score;
    sleeve.position.entry_conviction = output.conviction;
    sleeve.position.entry_mid_price = feature.mid_price;
    sleeve.position.entry_spread_bps = feature.spread_bps_1s;
    sleeve.position.weight = entry_weight;
    sleeve.position.entry_sequence = feature.sequence;
    sleeve.position.entry_timestamp_ns = feature.timestamp_ns;
    sleeve.position.entry_features = build_entry_feature_vector(feature, output, side).values;
}

hft::portfolio::RegimeInputs build_regime_inputs(const mm::FeatureEvent& feature,
                                                 const mm::StrategyOutput& mm_output,
                                                 const liquidity::StrategyOutput& liquidity_output,
                                                 const momentum::StrategyOutput& momentum_output,
                                                 double latency_us)
{
    const double spread_shock =
        std::max(0.0, feature.spread_bps_100ms - std::max(feature.spread_bps_1s, 1e-9));
    const double liquidity_stress =
        hft::portfolio::clamp01((std::abs(feature.imbalance_100ms) * 1.5) +
                                (std::abs(feature.microprice_edge_100ms_bps) * 0.8) +
                                (spread_shock * 0.5) +
                                (output_regime_quality(liquidity_output) * 0.25));
    const double momentum_pressure =
        hft::portfolio::clamp01((std::abs(momentum_output.score) * 1.2) +
                                (std::abs(feature.microprice_edge_100ms_bps) * 0.9) +
                                (output_regime_quality(momentum_output) * 0.25));
    const double market_making_quality =
        hft::portfolio::clamp01((feature.quote_rate_1s / 60.0) +
                                (mm_output.conviction * 0.35) -
                                (std::max(0.0, feature.spread_bps_1s - 1.2) * 0.25));
    return {liquidity_stress, momentum_pressure, market_making_quality, latency_us, 1.0};
}

bool decision_mode_disabled(const std::string& mode)
{
    return mode == "off" || mode == "none" || mode == "base";
}

bool decision_mode_uses_hmm(const std::string& mode)
{
    return mode == "hmm" || mode == "hmm-hawkes" || mode == "full";
}

bool decision_mode_uses_hawkes(const std::string& mode)
{
    return mode == "hmm-hawkes" || mode == "full";
}

bool decision_mode_uses_volatility(const std::string& mode)
{
    return mode == "full";
}

bool valid_decision_mode(const std::string& mode)
{
    return decision_mode_disabled(mode) ||
           mode == "hmm" ||
           mode == "hmm-hawkes" ||
           mode == "full";
}

struct DecisionControls
{
    std::array<double, 3> min_edge_bps{};
    std::array<double, 3> size_multiplier{};
};

decision_engine::regime_model::RegimeObservation build_regime_observation(
    const mm::FeatureEvent& feature,
    double volatility_bps)
{
    return {
        feature.spread_bps_1s,
        volatility_bps,
        feature.imbalance_1s,
        feature.microprice_edge_1s_bps,
        feature.quote_rate_1s,
    };
}

DecisionControls apply_decision_engine(const PortfolioConfig& config,
                                       const decision_engine::regime_model::RegimeOutput& regime,
                                       const decision_engine::event_intensity::IntensityOutput& intensity,
                                       const decision_engine::risk_model::VolatilityOutput& risk,
                                       double& market_making_target,
                                       double& liquidity_target,
                                       double& momentum_target)
{
    DecisionControls controls{
        {config.min_edge_bps, config.min_edge_bps, config.min_edge_bps},
        {1.0, 1.0, 1.0},
    };

    if (decision_mode_disabled(config.decision_mode)) {
        return controls;
    }

    using decision_engine::regime_model::RegimeState;
    if (decision_mode_uses_hmm(config.decision_mode)) {
        switch (regime.state) {
            case RegimeState::Stable:
                market_making_target = std::min(1.0, (market_making_target * 1.10) + 0.03);
                liquidity_target *= 0.70;
                momentum_target *= 0.55;
                controls.min_edge_bps[0] *= 0.90;
                controls.min_edge_bps[1] *= 1.20;
                controls.min_edge_bps[2] *= 1.30;
                break;
            case RegimeState::Directional:
                market_making_target *= 0.78;
                liquidity_target *= 0.75;
                momentum_target = std::min(0.12, std::max(momentum_target * 1.55, 0.035));
                controls.min_edge_bps[0] *= 1.05;
                controls.min_edge_bps[1] *= 1.10;
                controls.min_edge_bps[2] *= 0.88;
                break;
            case RegimeState::Stressed:
                market_making_target *= 0.55;
                liquidity_target *= 0.40;
                momentum_target *= 0.30;
                controls.min_edge_bps[0] *= 1.35;
                controls.min_edge_bps[1] *= 1.50;
                controls.min_edge_bps[2] *= 1.55;
                break;
        }
    }

    if (decision_mode_uses_hawkes(config.decision_mode)) {
        if (intensity.intensity_score < 0.95) {
            liquidity_target *= 0.60;
            momentum_target *= 0.35;
            controls.min_edge_bps[1] *= 1.15;
            controls.min_edge_bps[2] *= 1.25;
        } else if (intensity.intensity_score > 1.05) {
            if (regime.state == RegimeState::Directional) {
                momentum_target = std::min(0.14, std::max(momentum_target * 1.35, 0.05));
                controls.min_edge_bps[2] *= 0.92;
            } else if (regime.state == RegimeState::Stable) {
                market_making_target = std::min(1.0, market_making_target * 1.05);
                controls.min_edge_bps[0] *= 0.96;
            } else {
                controls.min_edge_bps[0] *= 1.08;
                controls.min_edge_bps[1] *= 1.08;
                controls.min_edge_bps[2] *= 1.08;
            }
        }
    }

    if (decision_mode_uses_volatility(config.decision_mode)) {
        controls.size_multiplier = {
            risk.size_multiplier,
            risk.size_multiplier,
            risk.size_multiplier,
        };
        if (risk.volatility_bps > 0.18) {
            controls.min_edge_bps[0] *= 1.10;
            controls.min_edge_bps[1] *= 1.20;
            controls.min_edge_bps[2] *= 1.20;
        }
    }

    market_making_target = std::max(0.0, market_making_target);
    liquidity_target = std::max(0.0, liquidity_target);
    momentum_target = std::max(0.0, momentum_target);
    return controls;
}

PortfolioStats run_portfolio_backtest(const std::string& csv_path,
                                      const PortfolioConfig& config)
{
    std::ifstream input(csv_path);
    if (!input) {
        throw std::runtime_error("Could not open CSV: " + csv_path);
    }
    if (config.forecast_mode != "heuristic" && config.forecast_mode != "ml") {
        throw std::runtime_error("forecast mode must be heuristic or ml");
    }
    if (config.portfolio_mode != "full" &&
        config.portfolio_mode != "mm-only" &&
        config.portfolio_mode != "liquidity-only" &&
        config.portfolio_mode != "momentum-only") {
        throw std::runtime_error("portfolio mode must be full, mm-only, liquidity-only, or momentum-only");
    }
    if (!valid_decision_mode(config.decision_mode)) {
        throw std::runtime_error("decision mode must be off, hmm, hmm-hawkes, or full");
    }

    MlModel ml_model;
    if (config.forecast_mode == "ml") {
        if (config.ml_model_path.empty()) {
            throw std::runtime_error("ML forecast mode requires --ml-model PATH");
        }
        ml_model.load(config.ml_model_path);
    }

    std::ofstream trade_export;
    const std::string trade_export_path = !config.trade_log_path.empty()
        ? config.trade_log_path
        : (config.output_prefix.empty() ? std::string{} : config.output_prefix + "_trades.csv");
    if (!trade_export_path.empty()) {
        trade_export.open(trade_export_path);
        if (!trade_export) {
            throw std::runtime_error("Could not open trade export: " + trade_export_path);
        }
        trade_export << std::fixed << std::setprecision(8);
        trade_export << "entry_timestamp_ns,exit_timestamp_ns,entry_event_index,exit_event_index,"
                     << "sleeve_id,sleeve,side,entry_reason,exit_reason,execution_type,"
                     << "portfolio_weight,forecast_edge_bps,"
                     << "signal_expected_edge_bps,ml_win_probability,score,conviction,"
                     << "entry_fill_price,exit_fill_price,entry_mid_price,exit_mid_price,"
                     << "entry_spread_bps,exit_spread_bps,gross_pnl_bps,transaction_cost_bps,"
                     << "execution_haircut_bps,adverse_selection_bps,net_pnl_bps,"
                     << "weighted_net_pnl_bps,sleeve_inventory_after_trade";
        for (const std::string& name : feature_names()) {
            trade_export << ",entry_feature_" << name;
        }
        trade_export << "\n";
    }

    std::ofstream rejected_export;
    if (!config.rejected_signals_path.empty()) {
        rejected_export.open(config.rejected_signals_path);
        if (!rejected_export) {
            throw std::runtime_error("Could not open rejected-signal export: " +
                                     config.rejected_signals_path);
        }
        rejected_export << std::fixed << std::setprecision(8);
        rejected_export << "timestamp_ns,event_index,sleeve_id,sleeve,side,reason,"
                        << "forecast_edge_bps,signal_expected_edge_bps,effective_min_edge_bps,"
                        << "score,conviction,spread_bps_1s,spread_bps_100ms,"
                        << "microprice_edge_100ms_bps,microprice_edge_1s_bps,"
                        << "quote_rate_1s,target_weight,fill_probability\n";
    }

    mm::FeatureBuilder mm_builder;
    liquidity::FeatureBuilder liquidity_builder;
    momentum::FeatureBuilder momentum_builder;
    decision_engine::regime_model::HiddenMarkovRegimeModel regime_model;
    decision_engine::event_intensity::HawkesIntensityModel intensity_model;
    decision_engine::risk_model::VolatilityRiskModel risk_model;

    mm::StrategyConfig mm_config;
    liquidity::StrategyConfig liquidity_config;
    momentum::StrategyConfig momentum_config;
    momentum_config.entry_threshold = std::max(momentum_config.entry_threshold, 1.30);
    momentum_config.min_expected_edge_bps = std::max(momentum_config.min_expected_edge_bps, 0.28);
    momentum_config.min_regime_quality = std::max(momentum_config.min_regime_quality, 0.95);
    momentum_config.min_directional_quality = std::max(momentum_config.min_directional_quality, 0.28);
    momentum_config.min_quote_rate_1s = std::max(momentum_config.min_quote_rate_1s, 32.0);
    momentum_config.max_hold_events = std::min<std::uint64_t>(momentum_config.max_hold_events, 7);

    mm::MicrostructureStrategy mm_engine(mm_config);
    liquidity::MicrostructureStrategy liquidity_engine(liquidity_config);
    momentum::MicrostructureStrategy momentum_engine(momentum_config);

    std::array<SleeveState, 3> sleeves = {
        SleeveState{"Market Making", RollingEdgeVariance(config.rolling_window), {}, 0, 0, 0, 0.0, 0.0},
        SleeveState{"Liquidity Detection", RollingEdgeVariance(config.rolling_window), {}, 0, 0, 0, 0.0, 0.0},
        SleeveState{"Momentum Ignition", RollingEdgeVariance(config.rolling_window), {}, 0, 0, 0, 0.0, 0.0},
    };

    PortfolioStats stats;
    std::vector<double> portfolio_returns_bps;
    std::vector<double> interval_returns_bps;
    std::vector<IntervalPoint> interval_points;
    double equity_bps = 0.0;
    double peak_bps = 0.0;
    double current_interval_return_bps = 0.0;
    std::uint64_t current_interval = 0;
    std::uint64_t sequence = 1;
    bool session_start_set = false;
    bool interval_initialized = false;
    std::mt19937_64 rng(config.seed);
    const std::uint64_t signal_latency_ns = config.signal_latency_us * 1000ULL;
    std::uint64_t latency_expired_signals = 0;
    std::deque<DelayedFeatureFrame> pending_frames;

    auto process_frame = [&](const mm::FeatureEvent& mm_feature,
                             const liquidity::FeatureEvent& liquidity_feature,
                             const momentum::FeatureEvent& momentum_feature) {
        if (!session_start_set) {
            mm_engine.set_session_start_timestamp_ns(mm_feature.timestamp_ns);
            liquidity_engine.set_session_start_timestamp_ns(liquidity_feature.timestamp_ns);
            momentum_engine.set_session_start_timestamp_ns(momentum_feature.timestamp_ns);
            session_start_set = true;
        }
        if (!interval_initialized) {
            current_interval = mm_feature.timestamp_ns / config.interval_ns;
            interval_initialized = true;
        } else {
            flush_return_intervals(interval_returns_bps,
                                   interval_points,
                                   current_interval,
                                   current_interval_return_bps,
                                   equity_bps,
                                   peak_bps,
                                   mm_feature.timestamp_ns,
                                   config.interval_ns);
        }

        mm_engine.on_feature(mm_feature);
        liquidity_engine.on_feature(liquidity_feature);
        momentum_engine.on_feature(momentum_feature);

        const mm::StrategyOutput mm_output = mm_engine.last_output();
        const liquidity::StrategyOutput liquidity_output = liquidity_engine.last_output();
        const momentum::StrategyOutput momentum_output = momentum_engine.last_output();

        const decision_engine::risk_model::VolatilityOutput risk_output =
            risk_model.update(mm_feature.timestamp_ns, mm_feature.mid_price);
        const decision_engine::regime_model::RegimeOutput regime_output =
            decision_mode_uses_hmm(config.decision_mode)
                ? regime_model.update(build_regime_observation(mm_feature, risk_output.volatility_bps))
                : decision_engine::regime_model::RegimeOutput{};
        const decision_engine::event_intensity::IntensityOutput intensity_output =
            decision_mode_uses_hawkes(config.decision_mode)
                ? intensity_model.update(mm_feature.timestamp_ns)
                : decision_engine::event_intensity::IntensityOutput{};

        const MlPrediction mm_prediction =
            build_edge_prediction(sleeves[0], mm_feature, mm_output, 0, config, ml_model);
        const MlPrediction liquidity_prediction =
            build_edge_prediction(sleeves[1], liquidity_feature, liquidity_output, 1, config, ml_model);
        const MlPrediction momentum_prediction =
            build_edge_prediction(sleeves[2], momentum_feature, momentum_output, 2, config, ml_model);

        const hft::portfolio::StrategyForecast mm_rolling =
            sleeves[0].edge_model.forecast(mm_output.expected_edge_bps);
        const hft::portfolio::StrategyForecast liquidity_rolling =
            sleeves[1].edge_model.forecast(liquidity_output.expected_edge_bps);
        const hft::portfolio::StrategyForecast momentum_rolling =
            sleeves[2].edge_model.forecast(momentum_output.expected_edge_bps);
        const hft::portfolio::ForecastSet forecasts{
            {mm_prediction.expected_edge_bps, mm_rolling.variance_bps2},
            {liquidity_prediction.expected_edge_bps, liquidity_rolling.variance_bps2},
            {momentum_prediction.expected_edge_bps, momentum_rolling.variance_bps2},
        };
        const hft::portfolio::StrategyWeights weights =
            hft::portfolio::allocate_adaptive(
                build_regime_inputs(mm_feature, mm_output, liquidity_output, momentum_output,
                                    static_cast<double>(config.signal_latency_us)),
                forecasts,
                config.forecast_weight);
        const bool strong_liquidity =
            output_regime_quality(liquidity_output) >= 1.25 &&
            liquidity_output.expected_edge_bps >= 0.32;
        const bool strong_momentum =
            output_regime_quality(momentum_output) >= 1.45 &&
            momentum_output.expected_edge_bps >= 0.38 &&
            std::abs(momentum_output.score) >= 0.35;
        double liquidity_target = 0.0;
        double momentum_target = 0.0;
        double market_making_target = 0.0;
        if (config.portfolio_mode == "mm-only") {
            market_making_target = 1.0;
        } else if (config.portfolio_mode == "liquidity-only") {
            liquidity_target = strong_liquidity
                ? std::min(1.0, std::max(0.35, weights.liquidity_detection))
                : 0.0;
        } else if (config.portfolio_mode == "momentum-only") {
            momentum_target = strong_momentum
                ? std::min(1.0, std::max(0.25, weights.momentum_ignition))
                : 0.0;
        } else {
            liquidity_target = std::min(weights.liquidity_detection, strong_liquidity ? 0.12 : 0.03);
            momentum_target = std::min(weights.momentum_ignition, strong_momentum ? 0.08 : 0.02);
            market_making_target =
                std::min(1.0, weights.market_making + (weights.liquidity_detection - liquidity_target) +
                                  (weights.momentum_ignition - momentum_target));
        }
        const DecisionControls decision_controls =
            config.portfolio_mode == "mm-only"
                ? DecisionControls{{config.min_edge_bps, config.min_edge_bps, config.min_edge_bps},
                                   {1.0, 1.0, 1.0}}
                : apply_decision_engine(config,
                                        regime_output,
                                        intensity_output,
                                        risk_output,
                                        market_making_target,
                                        liquidity_target,
                                        momentum_target);

        std::array<double, 3> closed_returns{};
        const std::string mm_exit_reason = sleeves[0].position.active
            ? position_exit_reason(sleeves[0].position, mm_feature, mm_output, true,
                                   mm_config.take_profit_bps, mm_config.stop_loss_bps,
                                   mm_config.max_hold_events)
            : std::string{};
        if (sleeves[0].position.active && !mm_exit_reason.empty()) {
            closed_returns[0] = close_position(sleeves[0], mm_feature, 0, true,
                                               mm_config.round_trip_cost_bps,
                                               config.adverse_selection_bps,
                                               mm_exit_reason,
                                               trade_export_path.empty() ? nullptr : &trade_export);
        }
        const std::string liquidity_exit_reason = sleeves[1].position.active
            ? position_exit_reason(sleeves[1].position, liquidity_feature, liquidity_output, false,
                                   liquidity_config.take_profit_bps, liquidity_config.stop_loss_bps,
                                   liquidity_config.max_hold_events)
            : std::string{};
        if (sleeves[1].position.active && !liquidity_exit_reason.empty()) {
            closed_returns[1] = close_position(sleeves[1], liquidity_feature, 1, false,
                                               liquidity_config.round_trip_cost_bps,
                                               config.adverse_selection_bps,
                                               liquidity_exit_reason,
                                               trade_export_path.empty() ? nullptr : &trade_export);
        }
        const std::string momentum_exit_reason = sleeves[2].position.active
            ? position_exit_reason(sleeves[2].position, momentum_feature, momentum_output, false,
                                   momentum_config.take_profit_bps, momentum_config.stop_loss_bps,
                                   momentum_config.max_hold_events)
            : std::string{};
        if (sleeves[2].position.active && !momentum_exit_reason.empty()) {
            closed_returns[2] = close_position(sleeves[2], momentum_feature, 2, false,
                                               momentum_config.round_trip_cost_bps,
                                               config.adverse_selection_bps,
                                               momentum_exit_reason,
                                               trade_export_path.empty() ? nullptr : &trade_export);
        }

        for (double closed_return : closed_returns) {
            if (closed_return == 0.0) {
                continue;
            }
            ++stats.completed_trades;
            if (closed_return > 0.0) {
                ++stats.winning_trades;
            }
            stats.total_net_return_bps += closed_return;
            equity_bps += closed_return;
            current_interval_return_bps += closed_return;
            peak_bps = std::max(peak_bps, equity_bps);
            stats.max_drawdown_bps = std::max(stats.max_drawdown_bps, peak_bps - equity_bps);
            portfolio_returns_bps.push_back(closed_return);
        }

        maybe_open_position(sleeves[0], mm_feature, mm_output, weights, market_making_target,
                            0, mm_prediction,
                            true, config,
                            decision_controls.min_edge_bps[0],
                            decision_controls.size_multiplier[0],
                            sleeves, rng,
                            config.rejected_signals_path.empty() ? nullptr : &rejected_export);
        maybe_open_position(sleeves[1], liquidity_feature, liquidity_output, weights,
                            liquidity_target, 1, liquidity_prediction, false, config,
                            decision_controls.min_edge_bps[1],
                            decision_controls.size_multiplier[1],
                            sleeves, rng,
                            config.rejected_signals_path.empty() ? nullptr : &rejected_export);
        maybe_open_position(sleeves[2], momentum_feature, momentum_output, weights,
                            momentum_target, 2, momentum_prediction, false, config,
                            decision_controls.min_edge_bps[2],
                            decision_controls.size_multiplier[2],
                            sleeves, rng,
                            config.rejected_signals_path.empty() ? nullptr : &rejected_export);

        ++stats.processed_quotes;
    };

    std::string line;
    std::uint64_t last_source_timestamp_ns = 0;
    while (std::getline(input, line)) {
        const std::optional<RawQuote> raw_quote = parse_quote_line(line);
        if (!raw_quote) {
            continue;
        }
        last_source_timestamp_ns = raw_quote->timestamp_ns;

        mm::QuoteEvent mm_quote;
        liquidity::QuoteEvent liquidity_quote;
        momentum::QuoteEvent momentum_quote;
        copy_quote(*raw_quote, mm_quote, sequence);
        copy_quote(*raw_quote, liquidity_quote, sequence);
        copy_quote(*raw_quote, momentum_quote, sequence);
        ++sequence;

        mm::FeatureEvent mm_feature;
        liquidity::FeatureEvent liquidity_feature;
        momentum::FeatureEvent momentum_feature;
        if (!mm_builder.on_quote(mm_quote, mm_feature) ||
            !liquidity_builder.on_quote(liquidity_quote, liquidity_feature) ||
            !momentum_builder.on_quote(momentum_quote, momentum_feature)) {
            continue;
        }

        mm_feature.timestamp_ns += signal_latency_ns;
        liquidity_feature.timestamp_ns += signal_latency_ns;
        momentum_feature.timestamp_ns += signal_latency_ns;
        pending_frames.push_back({mm_feature, liquidity_feature, momentum_feature});

        while (!pending_frames.empty() &&
               pending_frames.front().mm_feature.timestamp_ns <= raw_quote->timestamp_ns) {
            DelayedFeatureFrame frame = pending_frames.front();
            pending_frames.pop_front();
            process_frame(frame.mm_feature, frame.liquidity_feature, frame.momentum_feature);
        }
    }

    while (!pending_frames.empty()) {
        DelayedFeatureFrame frame = pending_frames.front();
        pending_frames.pop_front();
        if (frame.mm_feature.timestamp_ns > last_source_timestamp_ns) {
            ++latency_expired_signals;
            continue;
        }
        process_frame(frame.mm_feature, frame.liquidity_feature, frame.momentum_feature);
    }

    if (interval_initialized) {
        interval_returns_bps.push_back(current_interval_return_bps);
        interval_points.push_back({
            current_interval,
            current_interval * config.interval_ns,
            current_interval_return_bps,
            equity_bps,
            -(peak_bps - equity_bps),
        });
    }
    stats.trade_sharpe = compute_sharpe(portfolio_returns_bps);
    stats.trade_win_rate = stats.completed_trades > 0
        ? static_cast<double>(stats.winning_trades) / static_cast<double>(stats.completed_trades)
        : 0.0;
    stats.sharpe = compute_return_quality(interval_returns_bps);
    stats.return_intervals = static_cast<std::uint32_t>(interval_returns_bps.size());
    for (const SleeveState& sleeve : sleeves) {
        stats.skipped_low_edge += sleeve.skipped_low_edge;
        stats.missed_expected_edge_bps += sleeve.missed_expected_edge_bps;
    }
    stats.latency_expired_signals = static_cast<std::uint32_t>(latency_expired_signals);

    if (!config.output_prefix.empty()) {
        std::ofstream interval_export(config.output_prefix + "_intervals.csv");
        if (!interval_export) {
            throw std::runtime_error("Could not open interval export prefix: " + config.output_prefix);
        }
        interval_export << std::fixed << std::setprecision(8);
        interval_export << "interval_id,timestamp_ns,return_bps,equity_bps,drawdown_bps\n";
        for (const IntervalPoint& point : interval_points) {
            interval_export << point.interval_id << ","
                            << point.timestamp_ns << ","
                            << point.return_bps << ","
                            << point.equity_bps << ","
                            << point.drawdown_bps << "\n";
        }
    }

    std::cout << "sleeve=MarketMaking completed_trades=" << sleeves[0].completed_trades
              << " skipped_low_edge=" << sleeves[0].skipped_low_edge
              << " missed_expected_edge_bps=" << sleeves[0].missed_expected_edge_bps
              << " sleeve_net_return_bps=" << sleeves[0].total_net_return_bps << "\n";
    std::cout << "sleeve=LiquidityDetection completed_trades=" << sleeves[1].completed_trades
              << " skipped_low_edge=" << sleeves[1].skipped_low_edge
              << " missed_expected_edge_bps=" << sleeves[1].missed_expected_edge_bps
              << " sleeve_net_return_bps=" << sleeves[1].total_net_return_bps << "\n";
    std::cout << "sleeve=MomentumIgnition completed_trades=" << sleeves[2].completed_trades
              << " skipped_low_edge=" << sleeves[2].skipped_low_edge
              << " missed_expected_edge_bps=" << sleeves[2].missed_expected_edge_bps
              << " sleeve_net_return_bps=" << sleeves[2].total_net_return_bps << "\n";

    return stats;
}

void print_usage()
{
    std::cout << "Usage:\n"
              << "  Portfolio Backtest.exe quotes.csv [--rolling-window N] [--min-edge-bps BPS]\n"
              << "                         [--forecast-weight W] [--max-gross-exposure W]\n"
              << "                         [--min-reentry-events N] [--interval-seconds N]\n"
              << "                         [--seed N] [--forecast-mode heuristic|ml]\n"
              << "                         [--ml-model PATH] [--min-ml-win-prob P]\n"
              << "                         [--portfolio-mode full|mm-only|liquidity-only|momentum-only]\n"
              << "                         [--decision-mode off|hmm|hmm-hawkes|full]\n"
              << "                         [--output-prefix PATH]\n"
              << "                         [--trade-log-path PATH] [--rejected-signals-path PATH]\n"
              << "                         [--adverse-selection-bps BPS]\n"
              << "                         [--signal-latency-us US]\n"
              << "                         [--mm-min-entry-microprice-edge-100ms-bps BPS]\n"
              << "                         [--mm-min-entry-spread-100ms-bps BPS]\n"
              << "                         [--mm-max-entry-side-imbalance-1s X]\n";
}
} // namespace

int main(int argc, char** argv)
{
    if (argc < 2) {
        print_usage();
        return 1;
    }

    const std::string csv_path = argv[1];
    PortfolioConfig config;

    for (int i = 2; i < argc; ++i) {
        const std::string arg = argv[i];
        try {
            if (arg == "--rolling-window" && i + 1 < argc) {
                config.rolling_window = static_cast<std::size_t>(std::stoull(argv[++i]));
            } else if (arg == "--min-edge-bps" && i + 1 < argc) {
                config.min_edge_bps = std::stod(argv[++i]);
            } else if (arg == "--forecast-weight" && i + 1 < argc) {
                config.forecast_weight = hft::portfolio::clamp01(std::stod(argv[++i]));
            } else if (arg == "--max-gross-exposure" && i + 1 < argc) {
                config.max_gross_exposure = std::max(0.0, std::stod(argv[++i]));
            } else if (arg == "--min-reentry-events" && i + 1 < argc) {
                config.min_reentry_events = std::stoull(argv[++i]);
            } else if (arg == "--interval-seconds" && i + 1 < argc) {
                config.interval_ns = std::stoull(argv[++i]) * 1000000000ULL;
                if (config.interval_ns == 0) {
                    throw std::runtime_error("interval must be positive");
                }
            } else if (arg == "--seed" && i + 1 < argc) {
                config.seed = std::stoull(argv[++i]);
            } else if (arg == "--forecast-mode" && i + 1 < argc) {
                config.forecast_mode = argv[++i];
                for (char& ch : config.forecast_mode) {
                    ch = static_cast<char>(std::tolower(static_cast<unsigned char>(ch)));
                }
            } else if (arg == "--ml-model" && i + 1 < argc) {
                config.ml_model_path = argv[++i];
            } else if (arg == "--min-ml-win-prob" && i + 1 < argc) {
                config.min_ml_win_probability = hft::portfolio::clamp01(std::stod(argv[++i]));
            } else if (arg == "--portfolio-mode" && i + 1 < argc) {
                config.portfolio_mode = argv[++i];
                for (char& ch : config.portfolio_mode) {
                    ch = static_cast<char>(std::tolower(static_cast<unsigned char>(ch)));
                }
            } else if (arg == "--decision-mode" && i + 1 < argc) {
                config.decision_mode = argv[++i];
                for (char& ch : config.decision_mode) {
                    ch = static_cast<char>(std::tolower(static_cast<unsigned char>(ch)));
                }
            } else if (arg == "--output-prefix" && i + 1 < argc) {
                config.output_prefix = argv[++i];
            } else if (arg == "--trade-log-path" && i + 1 < argc) {
                config.trade_log_path = argv[++i];
            } else if (arg == "--rejected-signals-path" && i + 1 < argc) {
                config.rejected_signals_path = argv[++i];
            } else if (arg == "--adverse-selection-bps" && i + 1 < argc) {
                config.adverse_selection_bps = std::max(0.0, std::stod(argv[++i]));
            } else if (arg == "--signal-latency-us" && i + 1 < argc) {
                config.signal_latency_us = std::stoull(argv[++i]);
            } else if (arg == "--mm-min-entry-microprice-edge-100ms-bps" && i + 1 < argc) {
                config.mm_min_entry_microprice_edge_100ms_bps =
                    std::max(0.0, std::stod(argv[++i]));
            } else if (arg == "--mm-min-entry-spread-100ms-bps" && i + 1 < argc) {
                config.mm_min_entry_spread_100ms_bps =
                    std::max(0.0, std::stod(argv[++i]));
            } else if (arg == "--mm-max-entry-side-imbalance-1s" && i + 1 < argc) {
                config.mm_max_entry_side_imbalance_1s =
                    hft::portfolio::clamp01(std::stod(argv[++i]));
            } else {
                std::cerr << "Unknown or incomplete argument: " << arg << "\n";
                print_usage();
                return 1;
            }
        } catch (...) {
            std::cerr << "Invalid value for argument: " << arg << "\n";
            return 1;
        }
    }

    try {
        const PortfolioStats stats = run_portfolio_backtest(csv_path, config);
        std::cout << std::fixed << std::setprecision(4);
        std::cout << "Portfolio event-level backtest complete\n";
        std::cout << "forecast_mode=" << config.forecast_mode << "\n";
        std::cout << "portfolio_mode=" << config.portfolio_mode << "\n";
        std::cout << "decision_mode=" << config.decision_mode << "\n";
        std::cout << "adverse_selection_bps=" << config.adverse_selection_bps << "\n";
        std::cout << "signal_latency_us=" << config.signal_latency_us << "\n";
        std::cout << "mm_min_entry_microprice_edge_100ms_bps="
                  << config.mm_min_entry_microprice_edge_100ms_bps << "\n";
        std::cout << "mm_min_entry_spread_100ms_bps="
                  << config.mm_min_entry_spread_100ms_bps << "\n";
        std::cout << "mm_max_entry_side_imbalance_1s="
                  << config.mm_max_entry_side_imbalance_1s << "\n";
        std::cout << "processed_quotes=" << stats.processed_quotes << "\n";
        std::cout << "completed_trades=" << stats.completed_trades << "\n";
        std::cout << "winning_trades=" << stats.winning_trades << "\n";
        std::cout << "trade_win_rate=" << stats.trade_win_rate << "\n";
        std::cout << "skipped_low_edge=" << stats.skipped_low_edge << "\n";
        std::cout << "missed_expected_edge_bps=" << stats.missed_expected_edge_bps << "\n";
        std::cout << "latency_expired_signals=" << stats.latency_expired_signals << "\n";
        std::cout << "return_intervals=" << stats.return_intervals << "\n";
        std::cout << "total_net_return_bps=" << stats.total_net_return_bps << "\n";
        std::cout << "max_drawdown_bps=" << stats.max_drawdown_bps << "\n";
        std::cout << "minute_return_sharpe=" << stats.sharpe << "\n";
        std::cout << "trade_sharpe_reference=" << stats.trade_sharpe << "\n";
    } catch (const std::exception& ex) {
        std::cerr << ex.what() << "\n";
        return 1;
    }

    return 0;
}
