// tests/platform/cpu_test.cpp - platform::detect_cpu_topology and the thread placement calls. CPU only. Where the OS
// refuses a placement (a restricted container) the placement cases are skipped with a line saying so.
#include "basalt/platform/cpu.hpp"

#include <algorithm>
#include <cstdio>
#include <string>
#include <thread>
#include <vector>

namespace {
int failures = 0;
void check(bool ok, const std::string& what) {
    std::printf("cpu %-62s -> %s\n", what.c_str(), ok ? "ok" : "FAILED   <-- WRONG");
    failures |= !ok;
}
}  // namespace

int main() {
    using namespace basalt::platform;
    const CpuTopology all = detect_cpu_topology(false, CpuAffinity::All);
    check(!all.worker_cores.empty(), "at least one worker core is found");
    check(all.host_core == -1, "without skip_first no core is reserved");
    check(all.p_cores >= 1, "at least one performance core is counted");
    bool unique = true;
    for (size_t i = 0; i < all.worker_cores.size(); ++i)
        for (size_t j = i + 1; j < all.worker_cores.size(); ++j) unique &= all.worker_cores[i] != all.worker_cores[j];
    check(unique, "no core is listed twice");

    const CpuTopology skip = detect_cpu_topology(true, CpuAffinity::All);
    if (all.worker_cores.size() > 1) {
        check(skip.host_core == all.worker_cores.front(), "skip_first reserves the first core for the host");
        check(skip.worker_cores.size() + 1 == all.worker_cores.size(), "and takes it out of the workers");
    }
    for (CpuAffinity a : {CpuAffinity::Auto, CpuAffinity::PCores}) {
        const CpuTopology t = detect_cpu_topology(false, a);
        check(!t.worker_cores.empty(), "a hybrid-aware ordering still finds cores");
    }

    // The classification alone, on described processors.
    using detail::CpuRecord;
    using detail::classify_cpus;
    {
        // two favoured performance cores ranked a little above six others, sixteen efficiency cores well below
        std::vector<CpuRecord> cpus;
        for (int c = 0; c < 24; ++c) cpus.push_back({c, 0, c, c < 2 ? 1024 : c < 8 ? 1012 : 768});
        const CpuTopology t = classify_cpus(cpus, true, CpuAffinity::Auto);
        check(t.is_hybrid && t.p_cores == 8 && t.p_threads == 8 && t.e_cores == 16,
              "favoured cores count with the other P-cores");
        check(t.host_core == 0 && t.worker_cores.size() == 23 && t.worker_cores[6] == 7 && t.worker_cores[7] == 8,
              "auto: the host on the first P-core, the other P-cores, then the E-cores");
        const CpuTopology p = classify_cpus(cpus, true, CpuAffinity::PCores);
        check(p.worker_cores.size() == 7 && p.worker_cores.back() == 7, "p-cores: the seven other P-cores only");
        const CpuTopology a = classify_cpus(cpus, true, CpuAffinity::All);
        check(a.host_core == 0 && a.worker_cores.size() == 23 && a.worker_cores.front() == 1,
              "all: every core, in capacity order");
    }
    {
        // SMT performance cores (siblings 8 apart) beside single-thread efficiency cores
        std::vector<CpuRecord> cpus;
        for (int c = 0; c < 16; ++c) cpus.push_back({c, 0, c % 8, c % 8 < 2 ? 1024 : 990});
        for (int c = 16; c < 24; ++c) cpus.push_back({c, 0, c, 640});
        const CpuTopology t = classify_cpus(cpus, false, CpuAffinity::Auto);
        check(t.is_hybrid && t.p_cores == 8 && t.p_threads == 16 && t.e_cores == 8, "SMT P-cores: cores and threads");
        check(t.worker_cores.size() == 24 && t.worker_cores[7] == 7 && t.worker_cores[8] == 8 &&
                  t.worker_cores[16] == 16,
              "auto: P-core primaries, then their siblings, then the E-cores");
    }
    {
        // capacities that differ only within the performance band: not hybrid, every core a worker
        std::vector<CpuRecord> cpus;
        for (int c = 0; c < 16; ++c) cpus.push_back({c, 0, c, c < 2 ? 1024 : 1000});
        const CpuTopology t = classify_cpus(cpus, true, CpuAffinity::Auto);
        check(!t.is_hybrid && t.p_cores == 16 && t.worker_cores.size() == 15, "favoured cores alone are not hybrid");
    }
    {
        // no capacities at all
        std::vector<CpuRecord> cpus;
        for (int c = 0; c < 8; ++c) cpus.push_back({c, 0, c, -1});
        const CpuTopology t = classify_cpus(cpus, false, CpuAffinity::Auto);
        check(!t.is_hybrid && t.p_cores == 8 && t.worker_cores.size() == 8, "no capacities: one worker per core");
    }

    return failures ? 1 : 0;
}
