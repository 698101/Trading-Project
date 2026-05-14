// Consolidated risk, execution, allocation, and diagnostic helpers.
// Flattened from the original shared headers and decision-engine headers.

#include <algorithm>
#include <array>
#include <cmath>
#include <cstdint>
#include <iterator>
#include <string_view>
#include <vector>

// ---- BEGIN flattened from Shared\Ablation.h


enum class AblationMask : std::uint32_t
{
    None = 0,
    Microprice = 1u << 0,
    Imbalance = 1u << 1,
};

inline AblationMask operator|(AblationMask left, AblationMask right)
{
    return static_cast<AblationMask>(
        static_cast<std::uint32_t>(left) | static_cast<std::uint32_t>(right));
}

inline AblationMask& operator|=(AblationMask& left, AblationMask right)
{
    left = left | right;
    return left;
}

inline bool has_ablation(AblationMask mask, AblationMask test)
{
    return (static_cast<std::uint32_t>(mask) & static_cast<std::uint32_t>(test)) != 0;
}

inline AblationMask ablation_from_name(std::string_view name)
{
    if (name == "microprice") return AblationMask::Microprice;
    if (name == "imbalance") return AblationMask::Imbalance;
    return AblationMask::None;
}

template <typename FeatureEventT>
inline void apply_ablation(std::vector<FeatureEventT>& features, AblationMask mask)
{
    if (mask == AblationMask::None) {
        return;
    }

    for (FeatureEventT& feature : features) {
        if (has_ablation(mask, AblationMask::Microprice)) {
            feature.microprice_edge_100ms_bps = 0.0;
            feature.microprice_edge_1s_bps = 0.0;
        }
        if (has_ablation(mask, AblationMask::Imbalance)) {
            feature.imbalance_100ms = 0.0;
            feature.imbalance_1s = 0.0;
        }
    }
}

template <typename FeatureEventT>
inline void apply_signal_latency(std::vector<FeatureEventT>& features, std::uint64_t latency_us)
{
    if (latency_us == 0 || features.empty()) {
        return;
    }

    const std::uint64_t latency_ns = latency_us * 1000ULL;
    const std::vector<FeatureEventT> original = features;
    std::size_t delayed_index = 0;

    for (std::size_t current_index = 0; current_index < features.size(); ++current_index) {
        const std::uint64_t current_timestamp = original[current_index].timestamp_ns;
        while (delayed_index + 1 < original.size() &&
               original[delayed_index + 1].timestamp_ns + latency_ns <= current_timestamp) {
            ++delayed_index;
        }

        const FeatureEventT& delayed = original[delayed_index];
        features[current_index].spread_bps_100ms = delayed.spread_bps_100ms;
        features[current_index].spread_bps_1s = delayed.spread_bps_1s;
        features[current_index].imbalance_100ms = delayed.imbalance_100ms;
        features[current_index].imbalance_1s = delayed.imbalance_1s;
        features[current_index].microprice_edge_100ms_bps = delayed.microprice_edge_100ms_bps;
        features[current_index].microprice_edge_1s_bps = delayed.microprice_edge_1s_bps;
        features[current_index].quote_rate_1s = delayed.quote_rate_1s;
        features[current_index].avg_bid_size_1s = delayed.avg_bid_size_1s;
        features[current_index].avg_ask_size_1s = delayed.avg_ask_size_1s;
    }
}

template <typename CompletedTradeT>
inline void apply_capacity_impact(std::vector<CompletedTradeT>& trades,
                                  double capacity_units,
                                  double impact_bps_per_unit)
{
    const double extra_units = capacity_units > 1.0 ? (capacity_units - 1.0) : 0.0;
    const double impact_bps = extra_units * impact_bps_per_unit;
    if (impact_bps <= 0.0) {
        return;
    }

    for (CompletedTradeT& trade : trades) {
        trade.net_return_bps -= impact_bps;
    }
}
// ---- END flattened from Shared\Ablation.h

// ---- BEGIN flattened from Shared\Portfolio Allocation.h


namespace hft::portfolio {

struct RegimeInputs
{
    double liquidity_stress = 0.0;
    double momentum_pressure = 0.0;
    double market_making_quality = 0.0;
    double latency_us = 0.0;
    double capacity_units = 1.0;
};

struct StrategyWeights
{
    double market_making = 0.0;
    double liquidity_detection = 0.0;
    double momentum_ignition = 0.0;
};

struct StrategyForecast
{
    double expected_edge_bps = 0.0;
    double variance_bps2 = 1.0;
};

struct ForecastSet
{
    StrategyForecast market_making{};
    StrategyForecast liquidity_detection{};
    StrategyForecast momentum_ignition{};
};

inline double clamp01(double value)
{
    return std::clamp(value, 0.0, 1.0);
}

inline StrategyWeights normalize(StrategyWeights weights)
{
    weights.market_making = std::max(0.0, weights.market_making);
    weights.liquidity_detection = std::max(0.0, weights.liquidity_detection);
    weights.momentum_ignition = std::max(0.0, weights.momentum_ignition);

    const double total =
        weights.market_making + weights.liquidity_detection + weights.momentum_ignition;
    if (total <= 0.0) {
        return {0.70, 0.20, 0.10};
    }

    weights.market_making /= total;
    weights.liquidity_detection /= total;
    weights.momentum_ignition /= total;
    return weights;
}

inline double edge_variance_score(const StrategyForecast& forecast)
{
    if (!std::isfinite(forecast.expected_edge_bps) ||
        !std::isfinite(forecast.variance_bps2)) {
        return 0.0;
    }

    constexpr double variance_floor_bps2 = 1e-6;
    return std::max(0.0, forecast.expected_edge_bps) /
           std::max(variance_floor_bps2, forecast.variance_bps2);
}

inline StrategyWeights allocate_by_edge_variance(const ForecastSet& forecasts)
{
    return normalize({
        edge_variance_score(forecasts.market_making),
        edge_variance_score(forecasts.liquidity_detection),
        edge_variance_score(forecasts.momentum_ignition),
    });
}

inline StrategyWeights blend_allocations(StrategyWeights left,
                                         StrategyWeights right,
                                         double right_weight)
{
    const double blend = clamp01(right_weight);
    return normalize({
        (left.market_making * (1.0 - blend)) + (right.market_making * blend),
        (left.liquidity_detection * (1.0 - blend)) +
            (right.liquidity_detection * blend),
        (left.momentum_ignition * (1.0 - blend)) +
            (right.momentum_ignition * blend),
    });
}

inline StrategyWeights allocate_by_regime(const RegimeInputs& inputs)
{
    StrategyWeights weights{0.70, 0.20, 0.10};

    if (inputs.liquidity_stress >= 0.70) {
        weights = {0.25, 0.55, 0.20};
    } else if (inputs.momentum_pressure >= 0.70 && inputs.liquidity_stress >= 0.35) {
        weights = {0.30, 0.20, 0.50};
    } else if (inputs.market_making_quality >= 0.65) {
        weights = {0.80, 0.15, 0.05};
    }

    if (inputs.latency_us >= 100.0) {
        const double momentum_cut = weights.momentum_ignition * 0.50;
        weights.momentum_ignition -= momentum_cut;
        weights.market_making += momentum_cut * 0.70;
        weights.liquidity_detection += momentum_cut * 0.30;
    }

    if (inputs.capacity_units >= 10.0) {
        const double thin_edge_cut =
            (weights.momentum_ignition * 0.50) + (weights.liquidity_detection * 0.20);
        weights.momentum_ignition *= 0.50;
        weights.liquidity_detection *= 0.80;
        weights.market_making += thin_edge_cut;
    }

    return normalize(weights);
}

inline StrategyWeights allocate_adaptive(const RegimeInputs& inputs,
                                         const ForecastSet& forecasts,
                                         double forecast_weight = 0.70)
{
    return blend_allocations(allocate_by_regime(inputs),
                             allocate_by_edge_variance(forecasts),
                             forecast_weight);
}

} // namespace hft::portfolio
// ---- END flattened from Shared\Portfolio Allocation.h

// ---- BEGIN flattened from decision_engine\event_intensity\HawkesIntensityModel.h


namespace decision_engine::event_intensity {

struct IntensityOutput
{
    double intensity_per_second = 0.0;
    double baseline_per_second = 0.0;
    double intensity_score = 1.0;
};

class HawkesIntensityModel
{
public:
    IntensityOutput update(std::uint64_t timestamp_ns)
    {
        constexpr double ns_to_seconds = 1e-9;
        if (last_timestamp_ns_ == 0 || timestamp_ns <= last_timestamp_ns_) {
            last_timestamp_ns_ = timestamp_ns;
            excitation_ += excitation_jump_;
            return current_output();
        }

        const double dt_seconds =
            static_cast<double>(timestamp_ns - last_timestamp_ns_) * ns_to_seconds;
        last_timestamp_ns_ = timestamp_ns;

        const double decay = std::exp(-decay_rate_ * std::max(0.0, dt_seconds));
        excitation_ = (excitation_ * decay) + excitation_jump_;

        const double instantaneous_rate = dt_seconds > 0.0 ? 1.0 / dt_seconds : baseline_per_second_;
        if (!baseline_initialized_) {
            baseline_per_second_ = std::clamp(instantaneous_rate, 1.0, 5000.0);
            fast_rate_per_second_ = baseline_per_second_;
            baseline_initialized_ = true;
        } else {
            baseline_per_second_ =
                (baseline_per_second_ * baseline_decay_) +
                (std::clamp(instantaneous_rate, 1.0, 5000.0) * (1.0 - baseline_decay_));
            fast_rate_per_second_ =
                (fast_rate_per_second_ * fast_decay_) +
                (std::clamp(instantaneous_rate, 1.0, 5000.0) * (1.0 - fast_decay_));
        }

        return current_output();
    }

private:
    IntensityOutput current_output() const
    {
        const double intensity = baseline_per_second_ + excitation_;
        const double rate_ratio = fast_rate_per_second_ / std::max(1.0, baseline_per_second_);
        const double excitation_ratio = excitation_ / std::max(1.0, baseline_per_second_);
        const double score = (rate_ratio * 0.70) + ((1.0 + excitation_ratio) * 0.30);
        return {
            intensity,
            baseline_per_second_,
            std::clamp(score, 0.0, 3.0),
        };
    }

    std::uint64_t last_timestamp_ns_ = 0;
    bool baseline_initialized_ = false;
    double baseline_per_second_ = 50.0;
    double fast_rate_per_second_ = 50.0;
    double excitation_ = 0.0;
    double excitation_jump_ = 0.65;
    double decay_rate_ = 6.0;
    double baseline_decay_ = 0.995;
    double fast_decay_ = 0.90;
};

} // namespace decision_engine::event_intensity
// ---- END flattened from decision_engine\event_intensity\HawkesIntensityModel.h

// ---- BEGIN flattened from decision_engine\regime_model\HiddenMarkovRegimeModel.h


namespace decision_engine::regime_model {

enum class RegimeState : int
{
    Stable = 0,
    Stressed = 1,
    Directional = 2
};

struct RegimeObservation
{
    double spread_bps = 0.0;
    double volatility_bps = 0.0;
    double imbalance = 0.0;
    double microprice_edge_bps = 0.0;
    double quote_rate_1s = 0.0;
};

struct RegimeOutput
{
    RegimeState state = RegimeState::Stable;
    double stable_probability = 1.0;
    double stressed_probability = 0.0;
    double directional_probability = 0.0;
};

inline const char* label(RegimeState state)
{
    switch (state) {
        case RegimeState::Stable:
            return "stable";
        case RegimeState::Stressed:
            return "stressed";
        case RegimeState::Directional:
            return "directional";
    }
    return "stable";
}

class HiddenMarkovRegimeModel
{
public:
    RegimeOutput update(const RegimeObservation& observation)
    {
        const std::array<double, 3> predicted = {
            (probabilities_[0] * 0.92) + (probabilities_[1] * 0.05) + (probabilities_[2] * 0.07),
            (probabilities_[0] * 0.03) + (probabilities_[1] * 0.90) + (probabilities_[2] * 0.08),
            (probabilities_[0] * 0.05) + (probabilities_[1] * 0.05) + (probabilities_[2] * 0.85),
        };

        const std::array<double, 3> emission = emission_likelihoods(observation);
        std::array<double, 3> posterior = {
            predicted[0] * emission[0],
            predicted[1] * emission[1],
            predicted[2] * emission[2],
        };

        const double total = posterior[0] + posterior[1] + posterior[2];
        if (total > 0.0 && std::isfinite(total)) {
            posterior[0] /= total;
            posterior[1] /= total;
            posterior[2] /= total;
            probabilities_ = posterior;
        }

        RegimeOutput output;
        output.stable_probability = probabilities_[0];
        output.stressed_probability = probabilities_[1];
        output.directional_probability = probabilities_[2];

        const auto best = std::max_element(probabilities_.begin(), probabilities_.end());
        output.state = static_cast<RegimeState>(
            static_cast<int>(std::distance(probabilities_.begin(), best)));
        return output;
    }

    const std::array<double, 3>& probabilities() const
    {
        return probabilities_;
    }

private:
    static double clamp(double value, double low, double high)
    {
        return std::max(low, std::min(high, value));
    }

    static double gaussian_score(double value, double mean, double sigma)
    {
        const double safe_sigma = std::max(1e-6, sigma);
        const double z = (value - mean) / safe_sigma;
        return std::exp(-0.5 * z * z);
    }

    static std::array<double, 3> emission_likelihoods(const RegimeObservation& observation)
    {
        const double spread = clamp(observation.spread_bps / 2.0, 0.0, 3.0);
        const double volatility = clamp(observation.volatility_bps / 0.12, 0.0, 3.0);
        const double imbalance = clamp(std::abs(observation.imbalance), 0.0, 1.0);
        const double microprice = clamp(std::abs(observation.microprice_edge_bps) / 1.2, 0.0, 3.0);
        const double quote_rate = clamp(observation.quote_rate_1s / 120.0, 0.0, 3.0);

        const double stable =
            gaussian_score(spread, 0.20, 0.35) *
            gaussian_score(volatility, 0.15, 0.45) *
            gaussian_score(imbalance, 0.10, 0.30) *
            gaussian_score(microprice, 0.10, 0.40) *
            gaussian_score(quote_rate, 0.55, 0.55);

        const double stressed =
            gaussian_score(spread, 1.15, 0.85) *
            gaussian_score(volatility, 1.35, 0.85) *
            gaussian_score(quote_rate, 1.25, 0.85) *
            gaussian_score(microprice, 0.55, 0.80);

        const double directional =
            gaussian_score(imbalance, 0.70, 0.35) *
            gaussian_score(microprice, 0.85, 0.50) *
            gaussian_score(volatility, 0.70, 0.75) *
            gaussian_score(quote_rate, 0.90, 0.75);

        return {
            std::max(stable, 1e-9),
            std::max(stressed, 1e-9),
            std::max(directional, 1e-9),
        };
    }

    std::array<double, 3> probabilities_{0.80, 0.10, 0.10};
};

} // namespace decision_engine::regime_model
// ---- END flattened from decision_engine\regime_model\HiddenMarkovRegimeModel.h

// ---- BEGIN flattened from decision_engine\risk_model\VolatilityRiskModel.h


namespace decision_engine::risk_model {

struct VolatilityOutput
{
    double volatility_bps = 0.0;
    double size_multiplier = 1.0;
};

class VolatilityRiskModel
{
public:
    VolatilityOutput update(std::uint64_t timestamp_ns, double mid_price)
    {
        (void)timestamp_ns;
        if (mid_price <= 0.0 || !std::isfinite(mid_price)) {
            return current_output();
        }

        if (last_mid_price_ <= 0.0) {
            last_mid_price_ = mid_price;
            return current_output();
        }

        const double return_bps = ((mid_price - last_mid_price_) / last_mid_price_) * 10000.0;
        last_mid_price_ = mid_price;

        const double bounded_return_bps = std::clamp(return_bps, -5.0, 5.0);
        ewma_variance_bps2_ =
            (lambda_ * ewma_variance_bps2_) +
            ((1.0 - lambda_) * bounded_return_bps * bounded_return_bps);
        initialized_ = true;
        return current_output();
    }

private:
    VolatilityOutput current_output() const
    {
        const double volatility_bps = initialized_ ? std::sqrt(std::max(0.0, ewma_variance_bps2_)) : 0.0;
        const double raw_multiplier = target_volatility_bps_ / std::max(volatility_bps, target_volatility_bps_);
        return {
            volatility_bps,
            std::clamp(raw_multiplier, min_size_multiplier_, max_size_multiplier_),
        };
    }

    bool initialized_ = false;
    double last_mid_price_ = 0.0;
    double ewma_variance_bps2_ = 0.0;
    double lambda_ = 0.985;
    double target_volatility_bps_ = 0.08;
    double min_size_multiplier_ = 0.35;
    double max_size_multiplier_ = 1.0;
};

} // namespace decision_engine::risk_model
// ---- END flattened from decision_engine\risk_model\VolatilityRiskModel.h

