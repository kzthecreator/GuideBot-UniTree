#include "../action_sequence.hpp"

#include <cmath>
#include <fstream>
#include <stdexcept>
#include <string>
#include <sys/stat.h>
#include <unistd.h>

void require(bool condition) {
    if (!condition) throw std::runtime_error("action sequence test failed");
}

int main() {
    const std::string directory = std::string(__FILE__).substr(0, std::string(__FILE__).find_last_of('/'));
    const std::string fixture_dir = directory + "/fixtures";
    char temp_template[] = "/tmp/g1-motion-test-XXXXXX";
    const char* temp = mkdtemp(temp_template);
    require(temp != nullptr);
    const std::string root = temp;
    require(mkdir((root + "/reception").c_str(), 0700) == 0);
    for (const std::string name : {"phase_a", "phase_b", "phase_c", "phase_d"}) {
        std::ifstream source(fixture_dir + "/" + name + ".dat", std::ios::binary);
        std::ofstream target(root + "/reception/" + name + ".dat", std::ios::binary);
        target << source.rdbuf();
    }
    {
        std::ofstream catalog(root + "/catalog.json");
        catalog << R"({"schema_version":1,"actions":[{"name":"phase_a","category":"reception","priority":"P0","type":"motion"},{"name":"phase_b","category":"reception","priority":"P0","type":"motion"},{"name":"phase_c","category":"reception","priority":"P0","type":"motion"},{"name":"phase_d","category":"reception","priority":"P0","type":"motion"}]})";
    }
    motion_catalog::Library library{motion_catalog::Catalog::load(root + "/catalog.json", 4), root, root, false};
    const std::string request_text =
        R"({"标签":"介绍展示墙","动作":{"a":"phase_a","b":"phase_b","c":"phase_c","d":"phase_d"},"时间":{"a":2,"b":3,"c":1,"d":4}})";
    const auto request = action_sequence::parse(request_text);
    const auto resolved = action_sequence::resolve(request, library);
    require(request.label == "介绍展示墙");
    require(resolved.waypoints.size() == 5);
    require(resolved.phase_end[0] == 1 && resolved.phase_end[1] == 3);
    require(std::abs(resolved.waypoints[1].requested_duration - 1.5) < 1e-9);
    require(std::abs(resolved.waypoints[2].requested_duration - 1.5) < 1e-9);
    const standing_motion::ArmPose start{};
    const auto plan = standing_motion::make_plan(start, 0.0, 0.0, resolved.waypoints);
    const auto actual = action_sequence::actual_phase_durations(resolved, plan);
    require(actual[0] >= 2.0 && actual[1] >= 3.0 && actual[2] >= 1.0 && actual[3] >= 4.0);

    library.require_approved = true;
    bool rejected = false;
    try { library.load("phase_a"); } catch (const std::runtime_error&) { rejected = true; }
    require(rejected);
    {
        std::ofstream meta(root + "/phase_a.json");
        meta << "{\"schema_version\":2,\"name\":\"phase_a\",\"category\":\"reception\",\"robot_model\":\"G1-7DOF\",\"source\":\"teach_with_name\",\"status\":\"draft\",\"verified_by\":\"tester\",\"verified_at\":\"2026-11-11T00:00:00+08:00\",\"sha256\":\""
             << motion_catalog::sha256_file(root + "/reception/phase_a.dat")
             << "\",\"version\":1,\"scenes\":[\"reception\"],\"label\":\"test\",\"description\":\"\",\"movement_context\":\"stationary\"}";
    }
    rejected = false;
    try { library.load("phase_a"); } catch (const std::runtime_error&) { rejected = true; }
    require(rejected);
    {
        std::ofstream meta(root + "/phase_a.json");
        meta << "{\"schema_version\":2,\"name\":\"phase_a\",\"category\":\"reception\",\"robot_model\":\"G1-7DOF\",\"source\":\"teach_with_name\",\"status\":\"approved\",\"verified_by\":\"tester\",\"verified_at\":\"2026-11-11T00:00:00+08:00\",\"sha256\":\""
             << motion_catalog::sha256_file(root + "/reception/phase_a.dat")
             << "\",\"version\":1,\"scenes\":[\"reception\"],\"label\":\"test\",\"description\":\"\",\"movement_context\":\"stationary\"}";
    }
    require(library.load("phase_a").size() == 1);
    {
        std::ofstream changed(root + "/reception/phase_a.dat", std::ios::app);
        changed << "\n";
    }
    rejected = false;
    try { library.load("phase_a"); } catch (const std::runtime_error&) { rejected = true; }
    require(rejected);

    for (const std::string invalid : {
             R"({"动作":{"a":"phase_a"},"时间":{"a":1}})",
             R"({"动作":{"a":"phase_a","b":"phase_b","c":"phase_c","d":"../bad"},"时间":{"a":1,"b":1,"c":1,"d":1}})",
             R"({"动作":{"a":"phase_a","b":"phase_b","c":"phase_c","d":"phase_d"},"时间":{"a":1,"b":1,"c":0,"d":1}})"}) {
        bool rejected = false;
        try { action_sequence::parse(invalid); }
        catch (const std::runtime_error&) { rejected = true; }
        require(rejected);
    }
    return 0;
}
