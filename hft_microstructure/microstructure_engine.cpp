// Consolidated microstructure ingestion and quote tooling.
// Build with -DBUILD_DATA_FUNNEL or -DBUILD_QUOTE_DOWNLOADER for the corresponding legacy tool.

#if defined(BUILD_DATA_FUNNEL)
#include "strategies.cpp"
using QuoteEvent = mm::QuoteEvent;
using FeatureEvent = mm::FeatureEvent;
using StrategyOutput = mm::StrategyOutput;
using MicrostructureStrategy = mm::MicrostructureStrategy;

#include <algorithm>
#include <array>
#include <atomic>
#include <chrono>
#include <cstdint>
#include <cstdlib>
#include <cstring>
#include <fstream>
#include <iomanip>
#include <immintrin.h>
#include <iostream>
#include <cmath>
#include <sstream>
#include <string>
#include <string_view>
#include <thread>

#ifndef NOMINMAX
#define NOMINMAX
#endif
#include <winsock2.h>
#include <windows.h>

#include <ixwebsocket/IXWebSocket.h>

struct RawQuoteMessage
{
    std::uint64_t sequence = 0;
    std::uint64_t received_timestamp_ns = 0;
    std::uint16_t length = 0;
    std::array<char, 256> payload{};
};

struct IngressEvent
{
    bool normalized = false;
    RawQuoteMessage raw{};
    QuoteEvent quote{};
};

enum class FeedStatus : int
{
    Disconnected = 0,
    Connecting = 1,
    Authenticated = 2,
    Subscribed = 3,
    Live = 4,
    Stale = 5
};

namespace
{
constexpr std::size_t RING_BUFFER_SIZE = 65536;
constexpr std::uint64_t BUCKET_NS = 100000000ULL;
constexpr std::size_t BUCKET_COUNT = 50;
constexpr std::uint32_t SNAPSHOT_PUBLISH_INTERVAL = 32;
constexpr std::uint64_t FEED_STALE_NS = 3000000000ULL;
constexpr std::array<std::uint64_t, 14> HISTOGRAM_BOUNDS_NS = {
    250, 500, 1000, 2000, 5000, 10000, 20000,
    50000, 100000, 250000, 500000, 1000000, 2500000, UINT64_MAX
};

static_assert((RING_BUFFER_SIZE & (RING_BUFFER_SIZE - 1)) == 0,
              "RING_BUFFER_SIZE must be a power of two");

template <typename T>
struct RingBuffer
{
    std::array<T, RING_BUFFER_SIZE> buffer{};
    alignas(64) std::atomic<std::size_t> head{0};
    alignas(64) std::atomic<std::size_t> tail{0};

    bool push(const T& item)
    {
        const std::size_t current_head = head.load(std::memory_order_relaxed);
        const std::size_t next_head = (current_head + 1) & (RING_BUFFER_SIZE - 1);
        if (next_head == tail.load(std::memory_order_acquire)) {
            return false;
        }

        buffer[current_head] = item;
        head.store(next_head, std::memory_order_release);
        return true;
    }

    bool pop(T& item)
    {
        const std::size_t current_tail = tail.load(std::memory_order_relaxed);
        if (current_tail == head.load(std::memory_order_acquire)) {
            return false;
        }

        item = buffer[current_tail];
        tail.store((current_tail + 1) & (RING_BUFFER_SIZE - 1), std::memory_order_release);
        return true;
    }

    std::size_t size_approx() const
    {
        const std::size_t current_head = head.load(std::memory_order_acquire);
        const std::size_t current_tail = tail.load(std::memory_order_acquire);
        return (current_head - current_tail) & (RING_BUFFER_SIZE - 1);
    }
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

RingBuffer<IngressEvent> ingress_ring;
RingBuffer<QuoteEvent> quote_ring;
RingBuffer<FeatureEvent> feature_ring;

std::atomic<bool> pipeline_shutdown{false};
std::atomic<std::uint64_t> next_sequence{1};

std::atomic<std::uint64_t> ingested_events{0};
std::atomic<std::uint64_t> parsed_events{0};
std::atomic<std::uint64_t> feature_events{0};
std::atomic<std::uint64_t> strategy_events{0};
std::atomic<std::uint64_t> dropped_ingress{0};
std::atomic<std::uint64_t> dropped_quotes{0};
std::atomic<std::uint64_t> dropped_features{0};
std::atomic<std::uint64_t> parse_errors{0};
std::atomic<std::uint64_t> sequence_gaps{0};
std::atomic<std::uint64_t> out_of_order_events{0};

std::array<std::atomic<std::uint64_t>, HISTOGRAM_BOUNDS_NS.size()> parse_latency_hist{};
std::array<std::atomic<std::uint64_t>, HISTOGRAM_BOUNDS_NS.size()> feature_latency_hist{};

std::atomic<int> snapshot_feed_status{static_cast<int>(FeedStatus::Disconnected)};
std::atomic<std::uint64_t> last_provider_activity_ns{0};
std::atomic<std::uint64_t> last_quote_processed_ns{0};
std::array<char, 24> snapshot_provider_name{};
std::array<char, 16> snapshot_symbol{};

std::atomic<double> snapshot_bid_price{0.0};
std::atomic<double> snapshot_ask_price{0.0};
std::atomic<double> snapshot_bid_size{0.0};
std::atomic<double> snapshot_ask_size{0.0};
std::atomic<double> snapshot_mid_price{0.0};
std::atomic<double> snapshot_spread_bps_100ms{0.0};
std::atomic<double> snapshot_spread_bps_1s{0.0};
std::atomic<double> snapshot_imbalance_100ms{0.0};
std::atomic<double> snapshot_imbalance_1s{0.0};
std::atomic<double> snapshot_microprice_edge_100ms{0.0};
std::atomic<double> snapshot_microprice_edge_1s{0.0};
std::atomic<double> snapshot_quote_rate_1s{0.0};
std::atomic<double> snapshot_avg_bid_size_1s{0.0};
std::atomic<double> snapshot_avg_ask_size_1s{0.0};
std::atomic<int> snapshot_signal{static_cast<int>(SignalState::Neutral)};
std::atomic<double> snapshot_signal_score{0.0};

std::uint64_t now_ns()
{
    return static_cast<std::uint64_t>(
        std::chrono::duration_cast<std::chrono::nanoseconds>(
            std::chrono::steady_clock::now().time_since_epoch()).count());
}

void copy_symbol(std::array<char, 16>& target, std::string_view source)
{
    target.fill('\0');
    std::size_t count = target.size() - 1;
    if (source.size() < count) {
        count = source.size();
    }
    std::memcpy(target.data(), source.data(), count);
}

void copy_provider_name(std::string_view source)
{
    snapshot_provider_name.fill('\0');
    std::size_t count = snapshot_provider_name.size() - 1;
    if (source.size() < count) {
        count = source.size();
    }
    std::memcpy(snapshot_provider_name.data(), source.data(), count);
}

std::string array_to_string(const std::array<char, 16>& value)
{
    return std::string(value.data());
}

std::string provider_to_string()
{
    return std::string(snapshot_provider_name.data());
}

const char* feed_status_to_string(FeedStatus status)
{
    switch (status) {
        case FeedStatus::Connecting: return "CONNECTING";
        case FeedStatus::Authenticated: return "AUTHENTICATED";
        case FeedStatus::Subscribed: return "SUBSCRIBED";
        case FeedStatus::Live: return "LIVE";
        case FeedStatus::Stale: return "STALE";
        default: return "DISCONNECTED";
    }
}

const char* health_to_string(FeedStatus status,
                             std::size_t ingress_depth,
                             std::size_t quote_depth,
                             std::size_t feature_depth,
                             std::uint64_t dropped_total,
                             std::uint64_t parse_error_total)
{
    if (status == FeedStatus::Disconnected || status == FeedStatus::Stale) {
        return "DEGRADED";
    }
    if (dropped_total > 0 || parse_error_total > 0) {
        return "WARNING";
    }
    if (ingress_depth > 2048 || quote_depth > 2048 || feature_depth > 2048) {
        return "BACKLOG";
    }
    if (status == FeedStatus::Live || status == FeedStatus::Subscribed || status == FeedStatus::Authenticated) {
        return "OK";
    }
    return "STARTING";
}

const char* queue_health_to_string(std::size_t depth)
{
    if (depth == 0) {
        return "EMPTY";
    }
    if (depth < 256) {
        return "LOW";
    }
    if (depth < 2048) {
        return "MED";
    }
    return "HIGH";
}

void set_low_latency_thread_profile(std::uint32_t preferred_cpu)
{
    const DWORD processor_count = GetActiveProcessorCount(ALL_PROCESSOR_GROUPS);
    if (processor_count > preferred_cpu && preferred_cpu < sizeof(DWORD_PTR) * 8) {
        SetThreadAffinityMask(GetCurrentThread(), static_cast<DWORD_PTR>(1ULL << preferred_cpu));
    }
    SetThreadPriority(GetCurrentThread(), THREAD_PRIORITY_HIGHEST);
}

void record_histogram(std::array<std::atomic<std::uint64_t>, HISTOGRAM_BOUNDS_NS.size()>& histogram,
                      std::uint64_t latency_ns)
{
    for (std::size_t i = 0; i < HISTOGRAM_BOUNDS_NS.size(); ++i) {
        if (latency_ns <= HISTOGRAM_BOUNDS_NS[i]) {
            histogram[i].fetch_add(1, std::memory_order_relaxed);
            return;
        }
    }
}

double histogram_percentile_us(const std::array<std::atomic<std::uint64_t>, HISTOGRAM_BOUNDS_NS.size()>& histogram,
                               double percentile)
{
    std::uint64_t total = 0;
    for (const auto& bucket : histogram) {
        total += bucket.load(std::memory_order_relaxed);
    }
    if (total == 0) {
        return 0.0;
    }

    const std::uint64_t target = static_cast<std::uint64_t>(std::ceil(percentile * static_cast<double>(total)));
    std::uint64_t cumulative = 0;
    for (std::size_t i = 0; i < HISTOGRAM_BOUNDS_NS.size(); ++i) {
        cumulative += histogram[i].load(std::memory_order_relaxed);
        if (cumulative >= target) {
            return static_cast<double>(HISTOGRAM_BOUNDS_NS[i]) / 1000.0;
        }
    }
    return static_cast<double>(HISTOGRAM_BOUNDS_NS.back()) / 1000.0;
}

bool should_shutdown(const RingBuffer<IngressEvent>& ingress,
                     const RingBuffer<QuoteEvent>& quotes,
                     const RingBuffer<FeatureEvent>& features)
{
    return pipeline_shutdown.load(std::memory_order_relaxed) &&
           ingress.size_approx() == 0 &&
           quotes.size_approx() == 0 &&
           features.size_approx() == 0;
}

void idle_wait(std::uint32_t& idle_spins)
{
    ++idle_spins;
    if (idle_spins < 4096) {
        _mm_pause();
    } else if (idle_spins < 8192) {
        SwitchToThread();
    } else {
        Sleep(0);
        idle_spins = 0;
    }
}

bool parse_csv_quote_line(const std::string& line, QuoteEvent& quote)
{
    std::stringstream stream(line);
    std::string timestamp_token;
    std::string symbol_token;
    std::string bid_price_token;
    std::string ask_price_token;
    std::string bid_size_token;
    std::string ask_size_token;

    if (!std::getline(stream, timestamp_token, ',')) return false;
    if (!std::getline(stream, symbol_token, ',')) return false;
    if (!std::getline(stream, bid_price_token, ',')) return false;
    if (!std::getline(stream, ask_price_token, ',')) return false;
    if (!std::getline(stream, bid_size_token, ',')) return false;
    if (!std::getline(stream, ask_size_token, ',')) return false;

    try {
        quote.source_timestamp_ns = std::stoull(timestamp_token);
        quote.parsed_timestamp_ns = quote.source_timestamp_ns;
        quote.bid_price = std::stod(bid_price_token);
        quote.ask_price = std::stod(ask_price_token);
        quote.bid_size = std::stod(bid_size_token);
        quote.ask_size = std::stod(ask_size_token);
    } catch (...) {
        return false;
    }

    copy_symbol(quote.symbol, symbol_token);
    return true;
}

bool parse_json_number_field(std::string_view object, std::string_view key, double& value)
{
    const std::size_t key_pos = object.find(key);
    if (key_pos == std::string_view::npos) {
        return false;
    }

    std::size_t value_start = key_pos + key.size();
    std::size_t value_end = value_start;
    while (value_end < object.size()) {
        const char c = object[value_end];
        if ((c >= '0' && c <= '9') || c == '.' || c == '-' || c == '+' || c == 'e' || c == 'E') {
            ++value_end;
        } else {
            break;
        }
    }

    if (value_end == value_start) {
        return false;
    }

    std::string token(object.substr(value_start, value_end - value_start));
    char* parse_end = nullptr;
    value = std::strtod(token.c_str(), &parse_end);
    return parse_end != token.c_str();
}

bool parse_json_string_field(std::string_view object, std::string_view key, std::string_view& value)
{
    const std::size_t key_pos = object.find(key);
    if (key_pos == std::string_view::npos) {
        return false;
    }

    const std::size_t value_start = key_pos + key.size();
    const std::size_t value_end = object.find('"', value_start);
    if (value_end == std::string_view::npos) {
        return false;
    }

    value = object.substr(value_start, value_end - value_start);
    return true;
}

bool is_alpaca_authenticated_message(std::string_view object)
{
    return object.find("\"T\":\"success\"") != std::string_view::npos &&
           object.find("\"msg\":\"authenticated\"") != std::string_view::npos;
}

bool is_alpaca_subscribed_message(std::string_view object)
{
    return object.find("\"T\":\"subscription\"") != std::string_view::npos &&
           object.find("\"quotes\"") != std::string_view::npos;
}

bool normalize_alpaca_quote(std::string_view object, QuoteEvent& quote)
{
    if (object.find("\"T\":\"q\"") == std::string_view::npos) {
        return false;
    }

    std::string_view symbol;
    if (!parse_json_string_field(object, "\"S\":\"", symbol) ||
        !parse_json_number_field(object, "\"bp\":", quote.bid_price) ||
        !parse_json_number_field(object, "\"ap\":", quote.ask_price) ||
        !parse_json_number_field(object, "\"bs\":", quote.bid_size) ||
        !parse_json_number_field(object, "\"as\":", quote.ask_size)) {
        return false;
    }

    quote.parsed_timestamp_ns = now_ns();
    copy_symbol(quote.symbol, symbol);
    return quote.bid_price > 0.0 && quote.ask_price > 0.0;
}

void parser_loop()
{
    set_low_latency_thread_profile(1);

    std::uint64_t last_sequence_seen = 0;
    std::uint32_t idle_spins = 0;

    while (true) {
        if (should_shutdown(ingress_ring, quote_ring, feature_ring)) {
            break;
        }

        IngressEvent ingress;
        if (!ingress_ring.pop(ingress)) {
            idle_wait(idle_spins);
            continue;
        }
        idle_spins = 0;

        QuoteEvent quote{};
        if (ingress.normalized) {
            quote = ingress.quote;
        } else {
            quote.sequence = ingress.raw.sequence;
            quote.source_timestamp_ns = ingress.raw.received_timestamp_ns;
            if (!normalize_alpaca_quote(std::string_view(ingress.raw.payload.data(), ingress.raw.length), quote)) {
                parse_errors.fetch_add(1, std::memory_order_relaxed);
                continue;
            }
        }

        if (last_sequence_seen != 0) {
            if (quote.sequence <= last_sequence_seen) {
                out_of_order_events.fetch_add(1, std::memory_order_relaxed);
            } else if (quote.sequence != last_sequence_seen + 1) {
                sequence_gaps.fetch_add(quote.sequence - last_sequence_seen - 1, std::memory_order_relaxed);
            }
        }
        last_sequence_seen = quote.sequence;

        parsed_events.fetch_add(1, std::memory_order_relaxed);
        const std::uint64_t parse_latency_ns = quote.parsed_timestamp_ns - quote.source_timestamp_ns;
        record_histogram(parse_latency_hist, parse_latency_ns);

        if (!quote_ring.push(quote)) {
            dropped_quotes.fetch_add(1, std::memory_order_relaxed);
        }
    }
}

void feature_loop()
{
    set_low_latency_thread_profile(2);

    FeatureBuilder builder;
    std::uint32_t publish_counter = 0;
    std::uint32_t idle_spins = 0;

    while (true) {
        if (should_shutdown(ingress_ring, quote_ring, feature_ring)) {
            break;
        }

        QuoteEvent quote;
        if (!quote_ring.pop(quote)) {
            idle_wait(idle_spins);
            continue;
        }
        idle_spins = 0;

        FeatureEvent feature{};
        if (!builder.on_quote(quote, feature)) {
            continue;
        }

        feature_events.fetch_add(1, std::memory_order_relaxed);
        last_quote_processed_ns.store(now_ns(), std::memory_order_relaxed);
        snapshot_feed_status.store(static_cast<int>(FeedStatus::Live), std::memory_order_relaxed);

        const std::uint64_t feature_latency_ns = now_ns() - quote.parsed_timestamp_ns;
        record_histogram(feature_latency_hist, feature_latency_ns);

        ++publish_counter;
        if (publish_counter >= SNAPSHOT_PUBLISH_INTERVAL) {
            publish_counter = 0;
            snapshot_symbol = quote.symbol;
            snapshot_bid_price.store(feature.bid_price, std::memory_order_relaxed);
            snapshot_ask_price.store(feature.ask_price, std::memory_order_relaxed);
            snapshot_bid_size.store(feature.bid_size, std::memory_order_relaxed);
            snapshot_ask_size.store(feature.ask_size, std::memory_order_relaxed);
            snapshot_mid_price.store(feature.mid_price, std::memory_order_relaxed);
            snapshot_spread_bps_100ms.store(feature.spread_bps_100ms, std::memory_order_relaxed);
            snapshot_spread_bps_1s.store(feature.spread_bps_1s, std::memory_order_relaxed);
            snapshot_imbalance_100ms.store(feature.imbalance_100ms, std::memory_order_relaxed);
            snapshot_imbalance_1s.store(feature.imbalance_1s, std::memory_order_relaxed);
            snapshot_microprice_edge_100ms.store(feature.microprice_edge_100ms_bps, std::memory_order_relaxed);
            snapshot_microprice_edge_1s.store(feature.microprice_edge_1s_bps, std::memory_order_relaxed);
            snapshot_quote_rate_1s.store(feature.quote_rate_1s, std::memory_order_relaxed);
            snapshot_avg_bid_size_1s.store(feature.avg_bid_size_1s, std::memory_order_relaxed);
            snapshot_avg_ask_size_1s.store(feature.avg_ask_size_1s, std::memory_order_relaxed);
        }

        if (!feature_ring.push(feature)) {
            dropped_features.fetch_add(1, std::memory_order_relaxed);
        }
    }
}

void strategy_loop()
{
    set_low_latency_thread_profile(3);

    MicrostructureStrategy strategy;
    std::uint32_t idle_spins = 0;

    while (true) {
        if (should_shutdown(ingress_ring, quote_ring, feature_ring)) {
            break;
        }

        FeatureEvent feature{};
        if (!feature_ring.pop(feature)) {
            idle_wait(idle_spins);
            continue;
        }
        idle_spins = 0;

        strategy.on_feature(feature);
        strategy_events.fetch_add(1, std::memory_order_relaxed);
        const StrategyOutput& output = strategy.last_output();
        snapshot_signal.store(static_cast<int>(output.signal), std::memory_order_relaxed);
        snapshot_signal_score.store(output.score, std::memory_order_relaxed);
    }
}

void report_loop()
{
    set_low_latency_thread_profile(4);

    std::uint64_t last_ingested = 0;
    std::uint64_t last_parsed = 0;
    std::uint64_t last_featured = 0;
    std::uint64_t last_strategy = 0;
    std::uint64_t last_dropped_ingress = 0;
    std::uint64_t last_dropped_quotes = 0;
    std::uint64_t last_dropped_features = 0;

    while (!pipeline_shutdown.load(std::memory_order_relaxed) ||
           ingress_ring.size_approx() > 0 ||
           quote_ring.size_approx() > 0 ||
           feature_ring.size_approx() > 0) {
        std::this_thread::sleep_for(std::chrono::seconds(1));

        const std::uint64_t ingested = ingested_events.load(std::memory_order_relaxed);
        const std::uint64_t parsed = parsed_events.load(std::memory_order_relaxed);
        const std::uint64_t featured = feature_events.load(std::memory_order_relaxed);
        const std::uint64_t strategized = strategy_events.load(std::memory_order_relaxed);
        const std::uint64_t dropped_ingress_count = dropped_ingress.load(std::memory_order_relaxed);
        const std::uint64_t dropped_quote_count = dropped_quotes.load(std::memory_order_relaxed);
        const std::uint64_t dropped_feature_count = dropped_features.load(std::memory_order_relaxed);

        FeedStatus status = static_cast<FeedStatus>(snapshot_feed_status.load(std::memory_order_relaxed));
        const std::uint64_t now = now_ns();
        const std::uint64_t last_activity = last_provider_activity_ns.load(std::memory_order_relaxed);
        if (status == FeedStatus::Live &&
            last_activity > 0 &&
            now - last_activity > FEED_STALE_NS) {
            status = FeedStatus::Stale;
        }

        const std::size_t ingress_depth = ingress_ring.size_approx();
        const std::size_t quote_depth = quote_ring.size_approx();
        const std::size_t feature_depth = feature_ring.size_approx();
        const std::uint64_t dropped_total =
            dropped_ingress_count + dropped_quote_count + dropped_feature_count;
        const std::uint64_t last_quote_ns = last_quote_processed_ns.load(std::memory_order_relaxed);
        const double last_quote_age_ms =
            last_quote_ns > 0 && now >= last_quote_ns
                ? static_cast<double>(now - last_quote_ns) / 1000000.0
                : 0.0;
        const double parse_p50_us = histogram_percentile_us(parse_latency_hist, 0.50);
        const double parse_p99_us = histogram_percentile_us(parse_latency_hist, 0.99);
        const double feature_p50_us = histogram_percentile_us(feature_latency_hist, 0.50);
        const double feature_p99_us = histogram_percentile_us(feature_latency_hist, 0.99);
        const SignalState signal =
            static_cast<SignalState>(snapshot_signal.load(std::memory_order_relaxed));

        std::cout << std::fixed << std::setprecision(4)
                  << "\n==================== HFT FUNNEL DASHBOARD ====================\n"
                  << "feed      | provider=" << provider_to_string()
                  << " status=" << feed_status_to_string(status)
                  << " health=" << health_to_string(status,
                        ingress_depth,
                        quote_depth,
                        feature_depth,
                        dropped_total,
                        parse_errors.load(std::memory_order_relaxed))
                  << " symbol=" << array_to_string(snapshot_symbol)
                  << " last_quote_ms=" << last_quote_age_ms << "\n"
                  << "throughput| ingest/s=" << (ingested - last_ingested)
                  << " parse/s=" << (parsed - last_parsed)
                  << " feature/s=" << (featured - last_featured)
                  << " signal/s=" << (strategized - last_strategy) << "\n"
                  << "queues    | ingress=" << ingress_depth << "(" << queue_health_to_string(ingress_depth) << ")"
                  << " quote=" << quote_depth << "(" << queue_health_to_string(quote_depth) << ")"
                  << " feature=" << feature_depth << "(" << queue_health_to_string(feature_depth) << ")" << "\n"
                  << "latency   | parse_p50_us=" << parse_p50_us
                  << " parse_p99_us=" << parse_p99_us
                  << " feature_p50_us=" << feature_p50_us
                  << " feature_p99_us=" << feature_p99_us << "\n"
                  << "quality   | drop_ingress=" << (dropped_ingress_count - last_dropped_ingress)
                  << " drop_quote=" << (dropped_quote_count - last_dropped_quotes)
                  << " drop_feature=" << (dropped_feature_count - last_dropped_features)
                  << " parse_errors=" << parse_errors.load(std::memory_order_relaxed)
                  << " seq_gaps=" << sequence_gaps.load(std::memory_order_relaxed)
                  << " out_of_order=" << out_of_order_events.load(std::memory_order_relaxed) << "\n"
                  << "market    | bid=" << snapshot_bid_price.load(std::memory_order_relaxed)
                  << " ask=" << snapshot_ask_price.load(std::memory_order_relaxed)
                  << " bid_sz=" << snapshot_bid_size.load(std::memory_order_relaxed)
                  << " ask_sz=" << snapshot_ask_size.load(std::memory_order_relaxed)
                  << " mid=" << snapshot_mid_price.load(std::memory_order_relaxed) << "\n"
                  << "features  | spread_100ms_bps=" << snapshot_spread_bps_100ms.load(std::memory_order_relaxed)
                  << " spread_1s_bps=" << snapshot_spread_bps_1s.load(std::memory_order_relaxed)
                  << " imbalance_100ms=" << snapshot_imbalance_100ms.load(std::memory_order_relaxed)
                  << " imbalance_1s=" << snapshot_imbalance_1s.load(std::memory_order_relaxed) << "\n"
                  << "signal    | micro_100ms_bps=" << snapshot_microprice_edge_100ms.load(std::memory_order_relaxed)
                  << " micro_1s_bps=" << snapshot_microprice_edge_1s.load(std::memory_order_relaxed)
                  << " quote_rate_1s=" << snapshot_quote_rate_1s.load(std::memory_order_relaxed)
                  << " signal=" << signal_to_string(signal)
                  << " score=" << snapshot_signal_score.load(std::memory_order_relaxed)
                  << "\n=============================================================="
                  << std::endl;

        last_ingested = ingested;
        last_parsed = parsed;
        last_featured = featured;
        last_strategy = strategized;
        last_dropped_ingress = dropped_ingress_count;
        last_dropped_quotes = dropped_quote_count;
        last_dropped_features = dropped_feature_count;
    }
}

class MarketDataProvider
{
public:
    virtual ~MarketDataProvider() = default;
    virtual int run(const std::string& source) = 0;
    virtual const char* name() const = 0;
};

class CsvReplayProvider final : public MarketDataProvider
{
public:
    const char* name() const override
    {
        return "CSVReplay";
    }

    int run(const std::string& csv_path) override
    {
        copy_provider_name(name());
        snapshot_feed_status.store(static_cast<int>(FeedStatus::Live), std::memory_order_relaxed);

        std::ifstream input(csv_path);
        if (!input) {
            std::cerr << "Could not open CSV file: " << csv_path << "\n";
            return 1;
        }

        std::thread parser(parser_loop);
        std::thread feature(feature_loop);
        std::thread strategy(strategy_loop);
        std::thread reporter(report_loop);

        std::string line;
        while (std::getline(input, line)) {
            if (line.empty()) {
                continue;
            }
            if (line.find("timestamp_ns") != std::string::npos &&
                line.find("bid_price") != std::string::npos) {
                continue;
            }

            QuoteEvent quote{};
            if (!parse_csv_quote_line(line, quote)) {
                parse_errors.fetch_add(1, std::memory_order_relaxed);
                continue;
            }

            quote.sequence = next_sequence.fetch_add(1, std::memory_order_relaxed);
            IngressEvent ingress{};
            ingress.normalized = true;
            ingress.quote = quote;

            last_provider_activity_ns.store(now_ns(), std::memory_order_relaxed);
            ingested_events.fetch_add(1, std::memory_order_relaxed);
            if (!ingress_ring.push(ingress)) {
                dropped_ingress.fetch_add(1, std::memory_order_relaxed);
            }
        }

        while (ingress_ring.size_approx() > 0 || quote_ring.size_approx() > 0 || feature_ring.size_approx() > 0) {
            std::this_thread::sleep_for(std::chrono::milliseconds(10));
        }

        pipeline_shutdown.store(true, std::memory_order_relaxed);
        snapshot_feed_status.store(static_cast<int>(FeedStatus::Disconnected), std::memory_order_relaxed);

        parser.join();
        feature.join();
        strategy.join();
        reporter.join();
        return 0;
    }
};

class AlpacaLiveProvider final : public MarketDataProvider
{
public:
    const char* name() const override
    {
        return "AlpacaIEX";
    }

    int run(const std::string& symbol) override
    {
        copy_provider_name(name());
        snapshot_feed_status.store(static_cast<int>(FeedStatus::Connecting), std::memory_order_relaxed);
        set_low_latency_thread_profile(0);

        const char* api_key = std::getenv("APCA_API_KEY_ID");
        const char* api_secret = std::getenv("APCA_API_SECRET_KEY");
        if (api_key == nullptr || api_secret == nullptr) {
            std::cerr << "Set APCA_API_KEY_ID and APCA_API_SECRET_KEY first.\n";
            return 1;
        }

        std::thread parser(parser_loop);
        std::thread feature(feature_loop);
        std::thread strategy(strategy_loop);
        std::thread reporter(report_loop);

        ix::WebSocket ws;
        ws.setUrl("wss://stream.data.alpaca.markets/v2/iex");

        ws.setOnMessageCallback([&](const ix::WebSocketMessagePtr& msg) {
            last_provider_activity_ns.store(now_ns(), std::memory_order_relaxed);

            if (msg->type == ix::WebSocketMessageType::Open) {
                const std::string auth_message =
                    std::string("{\"action\":\"auth\",\"key\":\"") + api_key +
                    "\",\"secret\":\"" + api_secret + "\"}";
                ws.send(auth_message);
                return;
            }

            if (msg->type == ix::WebSocketMessageType::Message) {
                try {
                    std::string_view payload(msg->str);
                    std::size_t position = 0;
                    while (true) {
                        const std::size_t object_start = payload.find('{', position);
                        if (object_start == std::string_view::npos) {
                            break;
                        }
                        const std::size_t object_end = payload.find('}', object_start);
                        if (object_end == std::string_view::npos) {
                            break;
                        }

                        const std::string_view object =
                            payload.substr(object_start, object_end - object_start + 1);
                        if (is_alpaca_authenticated_message(object)) {
                            snapshot_feed_status.store(static_cast<int>(FeedStatus::Authenticated),
                                                       std::memory_order_relaxed);
                            const std::string subscribe_message =
                                std::string("{\"action\":\"subscribe\",\"quotes\":[\"") +
                                symbol + "\"]}";
                            ws.send(subscribe_message);
                            position = object_end + 1;
                            continue;
                        }

                        if (is_alpaca_subscribed_message(object)) {
                            snapshot_feed_status.store(static_cast<int>(FeedStatus::Subscribed),
                                                       std::memory_order_relaxed);
                            position = object_end + 1;
                            continue;
                        }

                        if (object.find("\"T\":\"q\"") == std::string_view::npos) {
                            position = object_end + 1;
                            continue;
                        }

                        RawQuoteMessage raw{};
                        const std::size_t object_size = object.size();
                        if (object_size >= raw.payload.size()) {
                            dropped_ingress.fetch_add(1, std::memory_order_relaxed);
                            position = object_end + 1;
                            continue;
                        }

                        raw.sequence = next_sequence.fetch_add(1, std::memory_order_relaxed);
                        raw.received_timestamp_ns = now_ns();
                        raw.length = static_cast<std::uint16_t>(object_size);
                        std::memcpy(raw.payload.data(), object.data(), object_size);

                        IngressEvent ingress{};
                        ingress.normalized = false;
                        ingress.raw = raw;

                        ingested_events.fetch_add(1, std::memory_order_relaxed);
                        if (!ingress_ring.push(ingress)) {
                            dropped_ingress.fetch_add(1, std::memory_order_relaxed);
                        }

                        position = object_end + 1;
                    }
                } catch (...) {
                    parse_errors.fetch_add(1, std::memory_order_relaxed);
                }
            } else if (msg->type == ix::WebSocketMessageType::Error) {
                std::cout << "feed_error=" << msg->errorInfo.reason << std::endl;
                snapshot_feed_status.store(static_cast<int>(FeedStatus::Disconnected),
                                           std::memory_order_relaxed);
            }
        });

        ws.start();

        parser.join();
        feature.join();
        strategy.join();
        reporter.join();
        return 0;
    }
};
} // namespace

int main(int argc, char** argv)
{
    WSADATA wsa_data;
    const int wsa_status = WSAStartup(MAKEWORD(2, 2), &wsa_data);
    if (wsa_status != 0) {
        std::cerr << "WSAStartup failed: " << wsa_status << "\n";
        return 1;
    }

    int exit_code = 0;
    if (argc > 2 && std::string_view(argv[1]) == "--replay") {
        CsvReplayProvider provider;
        exit_code = provider.run(argv[2]);
    } else if (argc > 2 && std::string_view(argv[1]) == "--live-alpaca") {
        AlpacaLiveProvider provider;
        exit_code = provider.run(argv[2]);
    } else {
        std::cout << "Top-of-book data funnel\n";
        std::cout << "Usage:\n";
        std::cout << "  Data Funnel.exe --live-alpaca SPY\n";
        std::cout << "  Data Funnel.exe --replay quotes.csv\n";
        std::cout << "CSV format: timestamp_ns,symbol,bid_price,ask_price,bid_size,ask_size\n";
    }

    WSACleanup();
    return exit_code;
}
#endif

#if defined(BUILD_QUOTE_DOWNLOADER)
#include <cstdint>
#include <cctype>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <cstdlib>
#include <sstream>
#include <string>
#include <vector>

#ifndef NOMINMAX
#define NOMINMAX
#endif
#include <windows.h>
#include <winhttp.h>

#pragma comment(lib, "winhttp.lib")

struct QuoteRow
{
    std::string timestamp;
    double bid_price = 0.0;
    double ask_price = 0.0;
    double bid_size = 0.0;
    double ask_size = 0.0;
};

std::wstring utf8_to_wide(const std::string& input)
{
    if (input.empty()) {
        return L"";
    }

    const int length = MultiByteToWideChar(CP_UTF8, 0, input.c_str(), -1, nullptr, 0);
    std::wstring output(static_cast<std::size_t>(length - 1), L'\0');
    MultiByteToWideChar(CP_UTF8, 0, input.c_str(), -1, output.data(), length);
    return output;
}

std::string wide_to_utf8(const std::wstring& input)
{
    if (input.empty()) {
        return "";
    }

    const int length = WideCharToMultiByte(CP_UTF8, 0, input.c_str(), -1, nullptr, 0, nullptr, nullptr);
    std::string output(static_cast<std::size_t>(length - 1), '\0');
    WideCharToMultiByte(CP_UTF8, 0, input.c_str(), -1, output.data(), length, nullptr, nullptr);
    return output;
}

std::string url_encode(const std::string& value)
{
    std::ostringstream encoded;
    encoded << std::uppercase << std::hex;
    for (unsigned char c : value) {
        if ((c >= 'a' && c <= 'z') ||
            (c >= 'A' && c <= 'Z') ||
            (c >= '0' && c <= '9') ||
            c == '-' || c == '_' || c == '.' || c == '~') {
            encoded << static_cast<char>(c);
        } else {
            encoded << '%' << std::setw(2) << std::setfill('0') << static_cast<int>(c);
        }
    }
    return encoded.str();
}

std::uint64_t iso8601_to_ns(const std::string& timestamp)
{
    if (timestamp.size() < 19) {
        return 0;
    }

    std::tm tm{};
    std::istringstream input(timestamp.substr(0, 19));
    input >> std::get_time(&tm, "%Y-%m-%dT%H:%M:%S");
    if (input.fail()) {
        return 0;
    }

#ifdef _WIN32
    const std::time_t epoch_seconds = _mkgmtime(&tm);
#else
    const std::time_t epoch_seconds = timegm(&tm);
#endif
    if (epoch_seconds < 0) {
        return 0;
    }

    std::uint64_t nanoseconds = static_cast<std::uint64_t>(epoch_seconds) * 1000000000ULL;
    const std::size_t dot_pos = timestamp.find('.');
    if (dot_pos != std::string::npos) {
        std::size_t end_pos = timestamp.find('Z', dot_pos);
        if (end_pos == std::string::npos) {
            end_pos = timestamp.size();
        }

        std::string fractional = timestamp.substr(dot_pos + 1, end_pos - dot_pos - 1);
        while (fractional.size() < 9) {
            fractional.push_back('0');
        }
        if (fractional.size() > 9) {
            fractional.resize(9);
        }
        nanoseconds += static_cast<std::uint64_t>(std::stoull(fractional));
    }

    return nanoseconds;
}

bool http_get(const std::wstring& host,
              const std::wstring& path_and_query,
              const std::string& api_key,
              const std::string& api_secret,
              std::string& response_body,
              DWORD& http_status_code)
{
    HINTERNET session = nullptr;
    HINTERNET connection = nullptr;
    HINTERNET request = nullptr;
    std::wstring headers;
    DWORD status_code = 0;
    DWORD status_code_size = sizeof(status_code);
    http_status_code = 0;

    session = WinHttpOpen(L"HFT Quote Downloader/1.0",
                          WINHTTP_ACCESS_TYPE_DEFAULT_PROXY,
                          WINHTTP_NO_PROXY_NAME,
                          WINHTTP_NO_PROXY_BYPASS,
                          0);
    if (!session) {
        return false;
    }

    connection = WinHttpConnect(session, host.c_str(), INTERNET_DEFAULT_HTTPS_PORT, 0);
    if (!connection) {
        WinHttpCloseHandle(session);
        return false;
    }

    request = WinHttpOpenRequest(connection,
                                 L"GET",
                                 path_and_query.c_str(),
                                 nullptr,
                                 WINHTTP_NO_REFERER,
                                 WINHTTP_DEFAULT_ACCEPT_TYPES,
                                 WINHTTP_FLAG_SECURE);
    if (!request) {
        WinHttpCloseHandle(connection);
        WinHttpCloseHandle(session);
        return false;
    }

    headers =
        L"APCA-API-KEY-ID: " + utf8_to_wide(api_key) + L"\r\n" +
        L"APCA-API-SECRET-KEY: " + utf8_to_wide(api_secret) + L"\r\n";

    if (!WinHttpSendRequest(request,
                            headers.c_str(),
                            static_cast<DWORD>(headers.size()),
                            WINHTTP_NO_REQUEST_DATA,
                            0,
                            0,
                            0)) {
        WinHttpCloseHandle(request);
        WinHttpCloseHandle(connection);
        WinHttpCloseHandle(session);
        return false;
    }

    if (!WinHttpReceiveResponse(request, nullptr)) {
        WinHttpCloseHandle(request);
        WinHttpCloseHandle(connection);
        WinHttpCloseHandle(session);
        return false;
    }

    if (!WinHttpQueryHeaders(request,
                             WINHTTP_QUERY_STATUS_CODE | WINHTTP_QUERY_FLAG_NUMBER,
                             WINHTTP_HEADER_NAME_BY_INDEX,
                             &status_code,
                             &status_code_size,
                             WINHTTP_NO_HEADER_INDEX)) {
        WinHttpCloseHandle(request);
        WinHttpCloseHandle(connection);
        WinHttpCloseHandle(session);
        return false;
    }

    http_status_code = status_code;
    if (status_code != 200) {
        WinHttpCloseHandle(request);
        WinHttpCloseHandle(connection);
        WinHttpCloseHandle(session);
        return false;
    }

    response_body.clear();
    while (true) {
        DWORD available_bytes = 0;
        if (!WinHttpQueryDataAvailable(request, &available_bytes)) {
            WinHttpCloseHandle(request);
            WinHttpCloseHandle(connection);
            WinHttpCloseHandle(session);
            return false;
        }

        if (available_bytes == 0) {
            break;
        }

        std::string buffer(available_bytes, '\0');
        DWORD downloaded_bytes = 0;
        if (!WinHttpReadData(request, buffer.data(), available_bytes, &downloaded_bytes)) {
            WinHttpCloseHandle(request);
            WinHttpCloseHandle(connection);
            WinHttpCloseHandle(session);
            return false;
        }

        buffer.resize(downloaded_bytes);
        response_body += buffer;
    }

    WinHttpCloseHandle(request);
    WinHttpCloseHandle(connection);
    WinHttpCloseHandle(session);
    return true;
}

std::size_t find_matching_bracket(const std::string& text, std::size_t open_pos, char open_char, char close_char)
{
    std::uint32_t depth = 0;
    bool in_string = false;
    bool escaped = false;

    for (std::size_t i = open_pos; i < text.size(); ++i) {
        const char ch = text[i];
        if (escaped) {
            escaped = false;
            continue;
        }
        if (ch == '\\' && in_string) {
            escaped = true;
            continue;
        }
        if (ch == '"') {
            in_string = !in_string;
            continue;
        }
        if (in_string) {
            continue;
        }
        if (ch == open_char) {
            ++depth;
        } else if (ch == close_char) {
            if (depth == 0) {
                return std::string::npos;
            }
            --depth;
            if (depth == 0) {
                return i;
            }
        }
    }

    return std::string::npos;
}

std::string extract_json_string_field(const std::string& object, const std::string& field)
{
    const std::string key = "\"" + field + "\"";
    const std::size_t key_pos = object.find(key);
    if (key_pos == std::string::npos) {
        return "";
    }
    const std::size_t colon_pos = object.find(':', key_pos + key.size());
    if (colon_pos == std::string::npos) {
        return "";
    }
    std::size_t quote_pos = colon_pos + 1;
    while (quote_pos < object.size() && std::isspace(static_cast<unsigned char>(object[quote_pos]))) {
        ++quote_pos;
    }
    if (quote_pos >= object.size() || object[quote_pos] != '"') {
        return "";
    }

    std::string value;
    bool escaped = false;
    for (std::size_t i = quote_pos + 1; i < object.size(); ++i) {
        const char ch = object[i];
        if (escaped) {
            value.push_back(ch);
            escaped = false;
            continue;
        }
        if (ch == '\\') {
            escaped = true;
            continue;
        }
        if (ch == '"') {
            return value;
        }
        value.push_back(ch);
    }

    return "";
}

double extract_json_number_field(const std::string& object, const std::string& field)
{
    const std::string key = "\"" + field + "\"";
    const std::size_t key_pos = object.find(key);
    if (key_pos == std::string::npos) {
        return 0.0;
    }
    const std::size_t colon_pos = object.find(':', key_pos + key.size());
    if (colon_pos == std::string::npos) {
        return 0.0;
    }
    std::size_t start = colon_pos + 1;
    while (start < object.size() && std::isspace(static_cast<unsigned char>(object[start]))) {
        ++start;
    }
    std::size_t end = start;
    while (end < object.size()) {
        const char ch = object[end];
        if (!(std::isdigit(static_cast<unsigned char>(ch)) || ch == '.' || ch == '-' || ch == '+' || ch == 'e' || ch == 'E')) {
            break;
        }
        ++end;
    }
    if (end == start) {
        return 0.0;
    }

    try {
        return std::stod(object.substr(start, end - start));
    } catch (...) {
        return 0.0;
    }
}

bool extract_symbol_quote_array(const std::string& payload,
                                const std::string& symbol,
                                std::string& array_payload)
{
    const std::string quotes_key = "\"quotes\"";
    const std::size_t quotes_pos = payload.find(quotes_key);
    if (quotes_pos == std::string::npos) {
        return false;
    }
    const std::string symbol_key = "\"" + symbol + "\"";
    const std::size_t symbol_pos = payload.find(symbol_key, quotes_pos + quotes_key.size());
    if (symbol_pos == std::string::npos) {
        return false;
    }
    const std::size_t array_start = payload.find('[', symbol_pos + symbol_key.size());
    if (array_start == std::string::npos) {
        return false;
    }
    const std::size_t array_end = find_matching_bracket(payload, array_start, '[', ']');
    if (array_end == std::string::npos) {
        return false;
    }

    array_payload = payload.substr(array_start + 1, array_end - array_start - 1);
    return true;
}

std::vector<QuoteRow> parse_quote_rows(const std::string& array_payload)
{
    std::vector<QuoteRow> rows;
    std::size_t scan_pos = 0;
    while (scan_pos < array_payload.size()) {
        const std::size_t object_start = array_payload.find('{', scan_pos);
        if (object_start == std::string::npos) {
            break;
        }
        const std::size_t object_end = find_matching_bracket(array_payload, object_start, '{', '}');
        if (object_end == std::string::npos) {
            break;
        }

        const std::string object = array_payload.substr(object_start, object_end - object_start + 1);
        QuoteRow row;
        row.timestamp = extract_json_string_field(object, "t");
        row.bid_price = extract_json_number_field(object, "bp");
        row.ask_price = extract_json_number_field(object, "ap");
        row.bid_size = extract_json_number_field(object, "bs");
        row.ask_size = extract_json_number_field(object, "as");
        rows.push_back(row);
        scan_pos = object_end + 1;
    }

    return rows;
}

int main(int argc, char** argv)
{
    if (argc < 5) {
        std::cout << "Usage:\n";
        std::cout << "  Quote Downloader.exe SYMBOL START_ISO END_ISO OUTPUT_CSV\n";
        std::cout << "Example:\n";
        std::cout << "  Quote Downloader.exe SPY 2026-04-15T13:30:00Z 2026-04-15T20:00:00Z quotes.csv\n";
        return 0;
    }

    const char* api_key = std::getenv("APCA_API_KEY_ID");
    const char* api_secret = std::getenv("APCA_API_SECRET_KEY");
    if (api_key == nullptr || api_secret == nullptr) {
        std::cerr << "Set APCA_API_KEY_ID and APCA_API_SECRET_KEY first.\n";
        return 1;
    }

    const std::string symbol = argv[1];
    const std::string start = argv[2];
    const std::string end = argv[3];
    const std::string output_path = argv[4];
    const char* page_limit_env = std::getenv("ALPACA_PAGE_LIMIT");
    const std::string page_limit = page_limit_env != nullptr ? page_limit_env : "10000";

    std::cout << "Starting historical quote download\n";
    std::cout << "symbol=" << symbol << "\n";
    std::cout << "start=" << start << "\n";
    std::cout << "end=" << end << "\n";
    std::cout << "output=" << output_path << "\n";

    std::ofstream output(output_path, std::ios::trunc);
    if (!output) {
        std::cerr << "Could not open output file: " << output_path << "\n";
        return 1;
    }

    output << "timestamp_ns,symbol,bid_price,ask_price,bid_size,ask_size\n";
    output << std::fixed << std::setprecision(6);

    std::uint64_t total_quotes = 0;
    std::string page_token;
    std::uint32_t page_number = 0;

    while (true) {
        ++page_number;
        std::string path =
            "/v2/stocks/quotes?symbols=" + url_encode(symbol) +
            "&start=" + url_encode(start) +
            "&end=" + url_encode(end) +
            "&feed=iex&limit=" + url_encode(page_limit) + "&sort=asc";

        if (!page_token.empty()) {
            path += "&page_token=" + url_encode(page_token);
        }

        std::cout << "Requesting page " << page_number;
        if (!page_token.empty()) {
            std::cout << " with page_token";
        }
        std::cout << "...\n";

        std::string response_body;
        DWORD http_status_code = 0;
        if (!http_get(L"data.alpaca.markets",
                      utf8_to_wide(path),
                      api_key,
                      api_secret,
                      response_body,
                      http_status_code)) {
            std::cerr << "HTTP request failed. status=" << http_status_code << "\n";
            return 1;
        }

        std::cout << "Received page " << page_number
                  << " bytes=" << response_body.size() << "\n";

        std::string quote_array_payload;
        if (!extract_symbol_quote_array(response_body, symbol, quote_array_payload)) {
            std::cerr << "No quotes returned for symbol " << symbol << "\n";
            return 1;
        }

        for (const QuoteRow& row : parse_quote_rows(quote_array_payload)) {
            if (!row.timestamp.empty() && row.bid_price > 0.0 && row.ask_price > row.bid_price) {
                output << iso8601_to_ns(row.timestamp) << ","
                       << symbol << ","
                       << row.bid_price << ","
                       << row.ask_price << ","
                       << row.bid_size << ","
                       << row.ask_size << "\n";
                ++total_quotes;
            }
        }

        output.flush();
        std::cout << "Accumulated quotes=" << total_quotes << "\n";

        page_token = extract_json_string_field(response_body, "next_page_token");
        if (page_token.empty()) {
            break;
        }
    }

    std::cout << "Downloaded " << total_quotes << " quotes to " << output_path << "\n";
    return 0;
}
#endif
