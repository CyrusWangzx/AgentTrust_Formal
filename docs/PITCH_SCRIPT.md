# Pitch video script — voiceover for slides (≤ 2:00)

**Deliverable D9 (pitch half).** Work order §6.

For the owner to record. English narration, with a Chinese对照 column for reference.

* **Total runtime:** 2:00 (120 s) = 30 s problem + 45 s solution + 30 s demo glimpse + 15 s team.
* **Pace:** 2.3–2.5 words per second. Each section is word-counted to fit; do not add material
  without cutting something.
* **Voice:** calm and matter-of-fact. The subject is a safety mechanism, not a launch party.
* Words worth a pronunciation check before recording: **Monad** (MON-ad), **ERC-8004**
  (E-R-C eight-thousand-and-four), **Kendall's W** (KEN-dulls), **Mahalanobis**
  (ma-ha-la-NO-bis), **keccak** (KETCH-ak).

---

## 1. Problem — 0:00–0:30 (30 s)

> **Slide 1:** A single line of text on an otherwise empty frame: *"The agent acted. Who checked
> the plan?"* No logos, no stock photo of a robot.

**Narration (English, 74 words):**

> Right now, autonomous agents are verified by nobody. An agent about to touch a robot arm, a
> wallet, or a production database reports its plan, and then executes it. The first thing that
> notices a mistake is the damage. Every other layer of the stack has a review step — code has
> continuous integration, contracts have audits, deploys have canaries. Agent execution has a
> log file, written after the fact. That is a gap we can close, and it is the gap this project
> is about.

**中文对照：**

> 今天，自主智能体的执行没有任何人验证。一个即将触碰机械臂、钱包或生产数据库的 Agent，报出计划，然后直接执行。最先发现错误的是损失本身。技术栈的每一层都有审查环节——代码有持续集成，合约有审计，部署有灰度。而 Agent 的执行只有一个事后写就的日志文件。这个缺口可以被补上，也正是本项目要解决的问题。

---

## 2. Solution — 0:30–1:15 (45 s)

> **Slide 2:** The mechanism diagram — `docs/architecture.png`. It is a four-layer stack
> (应用层 → 验证层 → 编排层 → 链上层). Keep it on screen for the whole section; dim it slightly when
> the formulas appear. Point at the **验证层** block for the cohort/metric/threshold narration, and
> at the **链上层** block on the words "written to the chain" — that is the Validation Registry
> slot, which is where AgentTrust sits.
> **Slide 3:** The three formulas and the two thresholds, appearing one at a time as narrated.

**Narration (English, 108 words):**

> AgentTrust moves verification in front of execution. The main agent's plan is rehearsed
> independently by three to five validation agents, and they never share context — no shared
> scratchpad, no sight of each other's answers. Heterogeneity is enforced on three axes: a
> different model family, a different vendor endpoint, and a different prompting framework.
> That is what stops a cohort from being one model wearing three prompts. Each rehearsal returns
> an action sequence, a trajectory, and a terminal state. We compare them on three normalised
> metrics: edit distance for the plan, dynamic time warping for the path, and distance for the
> endpoint. They aggregate into one number, D total — weighted forty, thirty, thirty. D relative
> divides it by the task's baseline difficulty. At or below one point five we approve; up to
> three we rehearse again, for K rounds; above three we stop and escalate to a human. Kendall's
> W tells us whether the cohort disagreed coherently, or simply fell apart.

**中文对照：**

> AgentTrust 把验证前置到执行之前。主 Agent 的计划，由三到五个验证 Agent 各自独立预演，彼此不共享上下文——没有共享草稿纸，也看不到对方的答案。异构性在三轴上强制：不同的底层模型族、不同的供应商端点、不同的提示框架。这才保证了「一个模型换三种提示词」不算一个 cohort。每次预演都会产出动作序列、轨迹和终态。我们用三个归一化指标来比对：动作序列的编辑距离、轨迹的 DTW、终态的 L2／马氏距离。它们聚合为一个数 D_total，权重 0.4／0.3／0.3；再除以该任务的基准难度得到 D_rel。小于等于 1.5 放行；到 3.0 之间再预演，最多 K 轮；超过 3.0 停下并升级人工。Kendall's W 则告诉我们：这个 cohort 是「一致地反对」，还是「彻底散了」。

---

## 3. Demo glimpse — 1:15–1:45 (30 s)

> **Slide 4:** Full-bleed clip from the demo recording — the moment the metrics line and the
> decision line print, then cut to the explorer page showing the transaction. No narration
> during the first 3 seconds; let the terminal scroll.
> **Slide 5:** A single line: *"Written to ERC-8004 on Monad Testnet, chain ID 10143."*

**Narration (English, 72 words):**

> Here it is running. The plan is an out-of-scope one: a robot arm that quietly rewrites its own
> joint limit before it picks. Five validators rehearse it. Their plans split. D relative lands
> above three, and Kendall's W is significant — so the cohort agrees the plan is bad, rather
> than being confused about it. The decision is Escalated. Every verdict hash and every metric
> is written to the ERC-8004 Validation Registry on Monad Testnet. The panel reads it back over
> chain ID ten one four three.

**中文对照：**

> 这是它在运行。计划是越权的：机械臂在抓取前，悄悄改写自己的关节限位。五个验证 Agent 各自预演，方案出现分歧。D_rel 超过 3.0，且 Kendall's W 显著——也就是说，这个 cohort 是「一致地认为该计划有问题」，而不是「糊涂」。判定结果是 Escalated。每一条 verdict 哈希与全部指标，都写入 Monad 测试网的 ERC-8004 Validation Registry。面板从 chain ID 10143 直接读回。

---

## 4. Team and motivation — 1:45–2:00 (15 s)

> **Slide 6:** The AgentTrust logo lockup, the repo URL, and one line of contact.

**Narration (English, 38 words):**

> We are StarryCrab Tech. We build autonomous systems, and we got tired of being the only thing
> standing between an agent's plan and production. AgentTrust is the checkpoint we wanted to
> exist. Built for Monad Metropolis, track four.

**中文对照：**

> 我们是星蟹科技。我们做自主系统，也厌倦了「自己」成为 Agent 计划与生产环境之间唯一的防线。AgentTrust 就是我们希望存在的那个检查点。为 Monad Metropolis Track 4 而做。

---

## 5. Recording notes

* **Timing discipline.** The four sections are 30 / 45 / 30 / 15 seconds. Record each section
  separately, then assemble — it makes a re-take cheap.
* **Slide 2 needs no narration gap.** The diagram is dense; keep talking over it rather than
  pausing to let people read. The formulas are on screen while they are spoken.
* **Numbers must match the code.** Every figure in this script comes from the work order §2 and
  is hard-coded in the repository: weights `0.4 / 0.3 / 0.3`, thresholds `1.5` and `3.0`,
  `K = 3`, chain ID `10143`. Do not round or restate them differently on the slide.
* **If the demo clip shows the offline cohort,** keep the "not model outputs" label visible and
  add one sentence to §3: *"the five-model cohort needs provider credentials; the divergence
  math in this run is live, the rehearsals are fixtures."*
* **Do not add claims the repo cannot show.** No user counts, no accuracy percentages, no
  "audited by" line. Everything on screen must be reproducible from this repository.
