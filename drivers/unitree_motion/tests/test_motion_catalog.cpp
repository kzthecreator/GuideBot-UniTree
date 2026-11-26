#include "motion_catalog.hpp"
#include <cstdio>
#include <unistd.h>

void require(bool value) {
    if (!value) throw std::runtime_error("catalog regression failed");
}

int main(int argc, char** argv) {
    require(argc == 2);
    const auto catalog = motion_catalog::Catalog::load(argv[1]);
    require(catalog.size() >= 30);
    const motion_catalog::Library library{catalog, "motions", "metadata", false, "poses"};
    require(library.motion_path(catalog.at("B_Neutral_Rest")) == "poses/basic/B_Neutral_Rest.dat");
    require(library.motion_path(catalog.at("B_Open_Hold")) == "motions/reception/B_Open_Hold.dat");
    for (const auto* name : {"Wave", "1_wave", "_wave", "123"})
        require(motion_catalog::valid_name(name));
    for (const auto* name : {"", "../bad", "bad/name", "bad name"})
        require(!motion_catalog::valid_name(name));
    for (const auto* name : {"B_Down_Beat", "B_Double_Beat", "R_Single_Beat",
                            "B_Open_Accent", "B_Forward_Accent", "B_Arc_Flow",
                            "R_Sweep_Flow", "B_Lower_Cadence"}) {
        const auto& entry = catalog.at(name);
        require(entry.category == "prosody" && entry.type == "motion");
        require(library.motion_path(entry) == std::string("motions/prosody/") + name + ".dat");
    }
    char path[] = "/tmp/guidebot-catalog-XXXXXX";
    const int fd = mkstemp(path);
    require(fd >= 0);
    close(fd);
    for (const auto* category : {"basic", "reception", "presentation", "interaction", "elevator", "prosody", "semantic", "invalid"}) {
        for (const auto* kind : {"pose", "motion"}) {
            nlohmann::json document = {{"schema_version", 1}, {"actions", nlohmann::json::array({
                {{"name", "example"}, {"category", category}, {"priority", "P1"}, {"type", kind}}
            })}};
            { std::ofstream out(path); out << document; }
            bool loaded = false;
            try { loaded = motion_catalog::Catalog::load(path).size() == 1; }
            catch (const std::runtime_error&) {}
            require(loaded == (std::string(category) != "invalid" &&
                ((std::string(kind) == "pose") == (std::string(category) == "basic"))));
        }
    }
    std::remove(path);
}
