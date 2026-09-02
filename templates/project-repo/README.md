# Student project repository — template

Everything in this directory belongs in a **student's** submission repo, not in
the grader repo. It lived under the grader's `.github/workflows/` at first,
where GitHub happily ran it on every push and it failed every time: it expects a
`GRADER_TOKEN` secret and a `GRADER_REPO` variable that only a student repo has.

To create the template repo:

```bash
mkdir project-template && cd project-template
cp -r ../cis677-hpcbench/templates/project-repo/. .
cp -r ../cis677-hpcbench/baselines/p1-kernel/. .
git init -b main && git add -A && git commit -m "P1 scaffold"
gh repo create gvsu-cis677/project-template --public --source=. --push
```

Then mark it as a template in **Settings → Template repository**, set the repo
variables `HANDLE`, `TASK_ID` and `GRADER_REPO`, and give each student a fork.
