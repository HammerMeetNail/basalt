# Upgrading from upstream

A deployment that carries its own commits keeps them on one branch and rebases that branch onto upstream for each
upgrade. There are no merge commits: the branch is always upstream plus its own commits on top. Settings stay in the
config file, which no upgrade touches; keep a setting there only when no code default covers it.

## Setup, once

```sh
git remote add upstream https://github.com/jesdga95/basalt
git fetch upstream
git switch -c perf upstream/main
git cherry-pick <your commits>
```

## Each upgrade

1. **Rebase.** Fetch upstream and replay the branch on its newest `main`:

   ```sh
   git fetch upstream
   git switch perf
   git rebase upstream/main
   ```

   A commit that upstream already contains drops out by itself. When upstream solved the same problem differently,
   the rebase stops on a conflict: keep upstream's version and drop yours with `git rebase --skip`.

2. **Build and test away from the running server.** A worktree builds the new tree without touching the deployed one:

   ```sh
   git worktree add ../basalt-next perf
   cmake -S ../basalt-next -B ../basalt-next/build -DBUILD_TESTING=ON <the deployment's other cmake options>
   cmake --build ../basalt-next/build -j
   ctest --test-dir ../basalt-next/build -L cpu
   ```

   Tests labelled `avx512` fail on a CPU without AVX-512; every other test must pass. Remove the worktree afterwards
   with `git worktree remove ../basalt-next`.

3. **Deploy with a way back.** In the deployed tree:
   - Wait until the server is idle: `/metrics` shows `live.state` `idle` and `queued` 0.
   - Copy `bin/` and the config file aside.
   - Check out the rebased branch and build: `cmake --build build -j`.
   - Restart the service and wait for `/health` to report `"loaded": true`.
   - Check that the engine's startup line `auto flags:` and the `engine` block of `/metrics` show what you expect.
   - If the server is not healthy or the values are wrong, put `bin/` and the config back and restart.

4. **Publish the branch,** if it lives on a fork. A rebase rewrites it, so the push needs a lease:

   ```sh
   git push --force-with-lease origin perf
   ```
