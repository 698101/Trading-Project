#include <algorithm>
#include <array>
#include <cmath>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <map>
#include <numeric>
#include <sstream>
#include <stdexcept>
#include <string>
#include <vector>

namespace
{
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

struct TrainingRow
{
    int sleeve_id = 0;
    std::array<double, kFeatureCount> features{};
    double realized_pnl_bps = 0.0;
};

struct ModelCoefficients
{
    double linear_intercept = 0.0;
    std::array<double, kFeatureCount> linear{};
    double logistic_intercept = 0.0;
    std::array<double, kFeatureCount> logistic{};
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

double mean(const std::vector<double>& values)
{
    if (values.empty()) {
        return 0.0;
    }
    return std::accumulate(values.begin(), values.end(), 0.0) /
           static_cast<double>(values.size());
}

double sample_stddev(const std::vector<double>& values)
{
    if (values.size() < 2) {
        return 0.0;
    }
    const double avg = mean(values);
    double variance = 0.0;
    for (double value : values) {
        const double diff = value - avg;
        variance += diff * diff;
    }
    variance /= static_cast<double>(values.size() - 1);
    return std::sqrt(variance);
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

double logit(double probability)
{
    const double clipped = std::clamp(probability, 1e-6, 1.0 - 1e-6);
    return std::log(clipped / (1.0 - clipped));
}

std::vector<double> solve_linear_system(std::vector<std::vector<double>> matrix,
                                        std::vector<double> rhs)
{
    const std::size_t n = rhs.size();
    for (std::size_t row = 0; row < n; ++row) {
        matrix[row].push_back(rhs[row]);
    }

    for (std::size_t col = 0; col < n; ++col) {
        std::size_t pivot = col;
        for (std::size_t row = col + 1; row < n; ++row) {
            if (std::abs(matrix[row][col]) > std::abs(matrix[pivot][col])) {
                pivot = row;
            }
        }
        if (std::abs(matrix[pivot][col]) < 1e-12) {
            continue;
        }
        if (pivot != col) {
            std::swap(matrix[pivot], matrix[col]);
        }

        const double pivot_value = matrix[col][col];
        for (std::size_t j = col; j <= n; ++j) {
            matrix[col][j] /= pivot_value;
        }
        for (std::size_t row = 0; row < n; ++row) {
            if (row == col) {
                continue;
            }
            const double factor = matrix[row][col];
            if (factor == 0.0) {
                continue;
            }
            for (std::size_t j = col; j <= n; ++j) {
                matrix[row][j] -= factor * matrix[col][j];
            }
        }
    }

    std::vector<double> solution(n, 0.0);
    for (std::size_t i = 0; i < n; ++i) {
        solution[i] = matrix[i][n];
    }
    return solution;
}

void standardize(const std::vector<TrainingRow>& rows,
                 std::vector<std::array<double, kFeatureCount>>& scaled,
                 std::array<double, kFeatureCount>& means,
                 std::array<double, kFeatureCount>& stddevs)
{
    for (std::size_t feature = 0; feature < kFeatureCount; ++feature) {
        std::vector<double> values;
        values.reserve(rows.size());
        for (const TrainingRow& row : rows) {
            values.push_back(row.features[feature]);
        }
        means[feature] = mean(values);
        stddevs[feature] = std::max(sample_stddev(values), 1.0e-9);
    }

    scaled.clear();
    scaled.reserve(rows.size());
    for (const TrainingRow& row : rows) {
        std::array<double, kFeatureCount> values{};
        for (std::size_t feature = 0; feature < kFeatureCount; ++feature) {
            values[feature] = (row.features[feature] - means[feature]) / stddevs[feature];
        }
        scaled.push_back(values);
    }
}

void convert_to_raw(const std::vector<double>& standardized,
                    const std::array<double, kFeatureCount>& means,
                    const std::array<double, kFeatureCount>& stddevs,
                    double& intercept,
                    std::array<double, kFeatureCount>& coefficients)
{
    intercept = standardized.empty() ? 0.0 : standardized[0];
    coefficients.fill(0.0);
    for (std::size_t feature = 0; feature < kFeatureCount; ++feature) {
        const double coefficient = standardized[feature + 1];
        coefficients[feature] = coefficient / stddevs[feature];
        intercept -= coefficient * means[feature] / stddevs[feature];
    }
}

void fit_linear(const std::vector<TrainingRow>& rows, ModelCoefficients& model)
{
    if (rows.size() < 8) {
        std::vector<double> targets;
        for (const TrainingRow& row : rows) {
            targets.push_back(row.realized_pnl_bps);
        }
        model.linear_intercept = mean(targets);
        model.linear.fill(0.0);
        return;
    }

    std::vector<std::array<double, kFeatureCount>> scaled;
    std::array<double, kFeatureCount> means{};
    std::array<double, kFeatureCount> stddevs{};
    standardize(rows, scaled, means, stddevs);

    constexpr std::size_t dimension = kFeatureCount + 1;
    std::vector<std::vector<double>> xtx(dimension, std::vector<double>(dimension, 0.0));
    std::vector<double> xty(dimension, 0.0);
    for (std::size_t row_index = 0; row_index < rows.size(); ++row_index) {
        std::array<double, dimension> values{};
        values[0] = 1.0;
        for (std::size_t feature = 0; feature < kFeatureCount; ++feature) {
            values[feature + 1] = scaled[row_index][feature];
        }

        for (std::size_t i = 0; i < dimension; ++i) {
            xty[i] += values[i] * rows[row_index].realized_pnl_bps;
            for (std::size_t j = 0; j < dimension; ++j) {
                xtx[i][j] += values[i] * values[j];
            }
        }
    }
    for (std::size_t i = 1; i < dimension; ++i) {
        xtx[i][i] += 0.25;
    }

    const std::vector<double> standardized_coefficients = solve_linear_system(xtx, xty);
    convert_to_raw(standardized_coefficients, means, stddevs,
                   model.linear_intercept, model.linear);
}

void fit_logistic(const std::vector<TrainingRow>& rows, ModelCoefficients& model)
{
    if (rows.empty()) {
        model.logistic_intercept = 0.0;
        model.logistic.fill(0.0);
        return;
    }

    std::vector<double> labels;
    labels.reserve(rows.size());
    for (const TrainingRow& row : rows) {
        labels.push_back(row.realized_pnl_bps > 0.0 ? 1.0 : 0.0);
    }

    const double win_rate = (std::accumulate(labels.begin(), labels.end(), 0.0) + 1.0) /
                            (static_cast<double>(labels.size()) + 2.0);
    const auto [min_label, max_label] = std::minmax_element(labels.begin(), labels.end());
    if (rows.size() < 12 || *min_label == *max_label) {
        model.logistic_intercept = logit(win_rate);
        model.logistic.fill(0.0);
        return;
    }

    std::vector<std::array<double, kFeatureCount>> scaled;
    std::array<double, kFeatureCount> means{};
    std::array<double, kFeatureCount> stddevs{};
    standardize(rows, scaled, means, stddevs);

    constexpr std::size_t dimension = kFeatureCount + 1;
    std::vector<double> weights(dimension, 0.0);
    weights[0] = logit(win_rate);
    constexpr double learning_rate = 0.12;
    constexpr double l2 = 0.01;

    for (std::size_t iteration = 0; iteration < 700; ++iteration) {
        std::vector<double> gradient(dimension, 0.0);
        for (std::size_t row_index = 0; row_index < rows.size(); ++row_index) {
            std::array<double, dimension> values{};
            values[0] = 1.0;
            for (std::size_t feature = 0; feature < kFeatureCount; ++feature) {
                values[feature + 1] = scaled[row_index][feature];
            }

            double log_odds = 0.0;
            for (std::size_t i = 0; i < dimension; ++i) {
                log_odds += weights[i] * values[i];
            }
            const double error = logistic(log_odds) - labels[row_index];
            for (std::size_t i = 0; i < dimension; ++i) {
                gradient[i] += error * values[i];
            }
        }

        const double inv_n = 1.0 / static_cast<double>(rows.size());
        for (std::size_t i = 0; i < dimension; ++i) {
            const double penalty = i == 0 ? 0.0 : l2 * weights[i];
            weights[i] -= learning_rate * ((gradient[i] * inv_n) + penalty);
        }
    }

    convert_to_raw(weights, means, stddevs, model.logistic_intercept, model.logistic);
}

std::vector<TrainingRow> load_training_rows(const std::vector<std::string>& paths)
{
    std::vector<TrainingRow> rows;
    for (const std::string& path : paths) {
        std::ifstream input(path);
        if (!input) {
            std::cerr << "Skipping missing trade file: " << path << "\n";
            continue;
        }

        std::string header_line;
        if (!std::getline(input, header_line)) {
            continue;
        }
        const std::vector<std::string> headers = split_csv_line(header_line);
        std::map<std::string, std::size_t> index;
        for (std::size_t i = 0; i < headers.size(); ++i) {
            index[headers[i]] = i;
        }
        if (!index.contains("sleeve_id") || !index.contains("realized_pnl_bps")) {
            continue;
        }

        std::string line;
        while (std::getline(input, line)) {
            if (line.empty()) {
                continue;
            }
            const std::vector<std::string> columns = split_csv_line(line);
            if (columns.size() < headers.size()) {
                continue;
            }

            TrainingRow row;
            row.sleeve_id = std::stoi(columns[index["sleeve_id"]]);
            row.realized_pnl_bps = std::stod(columns[index["realized_pnl_bps"]]);
            bool ok = true;
            for (std::size_t feature = 0; feature < kFeatureCount; ++feature) {
                const std::string& name = feature_names()[feature];
                if (!index.contains(name)) {
                    ok = false;
                    break;
                }
                row.features[feature] = std::stod(columns[index[name]]);
            }
            if (ok && row.sleeve_id >= 0 && row.sleeve_id < 3) {
                rows.push_back(row);
            }
        }
    }
    return rows;
}

void write_model(const std::string& path,
                 const std::array<ModelCoefficients, 3>& models)
{
    std::ofstream output(path);
    if (!output) {
        throw std::runtime_error("Could not open model output: " + path);
    }
    output << std::fixed << std::setprecision(10);
    output << "sleeve,linear_intercept";
    for (const std::string& name : feature_names()) {
        output << ",linear_" << name;
    }
    output << ",logistic_intercept";
    for (const std::string& name : feature_names()) {
        output << ",logistic_" << name;
    }
    output << "\n";

    for (std::size_t sleeve = 0; sleeve < models.size(); ++sleeve) {
        output << sleeve << "," << models[sleeve].linear_intercept;
        for (double value : models[sleeve].linear) {
            output << "," << value;
        }
        output << "," << models[sleeve].logistic_intercept;
        for (double value : models[sleeve].logistic) {
            output << "," << value;
        }
        output << "\n";
    }
}

} // namespace

int main(int argc, char** argv)
{
    if (argc < 3) {
        std::cerr << "Usage:\n"
                  << "  ML Trainer.exe OUTPUT_MODEL.csv TRADE_FILE_1.csv [TRADE_FILE_2.csv ...]\n";
        return 1;
    }

    try {
        std::vector<std::string> trade_paths;
        for (int i = 2; i < argc; ++i) {
            trade_paths.push_back(argv[i]);
        }

        const std::vector<TrainingRow> rows = load_training_rows(trade_paths);
        std::array<ModelCoefficients, 3> models{};
        for (int sleeve = 0; sleeve < 3; ++sleeve) {
            std::vector<TrainingRow> sleeve_rows;
            for (const TrainingRow& row : rows) {
                if (row.sleeve_id == sleeve) {
                    sleeve_rows.push_back(row);
                }
            }
            fit_linear(sleeve_rows, models[static_cast<std::size_t>(sleeve)]);
            fit_logistic(sleeve_rows, models[static_cast<std::size_t>(sleeve)]);
            std::cout << "sleeve=" << sleeve
                      << " training_rows=" << sleeve_rows.size() << "\n";
        }
        write_model(argv[1], models);
        std::cout << "total_training_rows=" << rows.size() << "\n";
        std::cout << "model_output=" << argv[1] << "\n";
    } catch (const std::exception& ex) {
        std::cerr << ex.what() << "\n";
        return 1;
    }

    return 0;
}
