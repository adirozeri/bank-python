# The Practical Test Pyramid — Study Notes

> Summary of Martin Fowler's article by Ham Vocke:
> https://martinfowler.com/articles/practical-test-pyramid.html
>
> Philosophy trimmed. **🔧 = practical / actionable.** Rules of thumb kept verbatim where useful.

---

## 1. The Core Idea

- The **Test Pyramid** is a metaphor for grouping tests by granularity and deciding **how many** of each to write.
- Original model (Mike Cohn), bottom → top:
  - **Unit Tests** (base — the most)
  - **Service Tests** (middle — some)
  - **UI Tests** (top — the fewest)
- 🔧 **Golden rule:** *"Write lots of small and fast unit tests. Write some more coarse-grained tests and very few high-level tests that test your application from end to end."*
- Two takeaways from the shape:
  - 🔧 Write tests at **different granularities**.
  - 🔧 The **higher** you go, the **fewer** tests you should have (they're slower + more brittle).

### Why automate at all
- Manual testing is slow, repetitive, error-prone.
- Automated tests = **fast feedback loop** → enables refactoring, Continuous Delivery, DevOps.
- Goal: find out you broke something in **seconds**, not days.

---

## 2. Unit Tests (base layer)

### What is a "unit"?
- Functional languages → usually a single **function**.
- OO languages → a single **method** up to a whole **class**.
- 🔧 Test the **public interface** of a class/unit.

### Solitary vs. Sociable
- **Solitary:** replace *all* collaborators with mocks/stubs → perfect isolation.
- **Sociable:** use **real** collaborators; only stub the slow / side-effecting ones (DB, network).
- 🔧 The author uses **both** depending on context — not dogmatic.

### Test Doubles (mocking & stubbing)
- A **Test Double** replaces a real object with a fake that returns canned responses.
- Tool example: **Mockito** (JVM mocking). JUnit as the runner.

### 🔧 What to test (and NOT test)
- ✅ Test **observable behavior**, not implementation details.
- ❌ Don't test trivial code: plain getters/setters with no logic. *"Don't worry, Kent Beck said it's ok."*
- ❌ Don't test **private methods** directly.
  - If you *really* feel you need to → it's a smell. The private method is probably too complex.
  - 🔧 **Fix:** split the class into two classes; the logic becomes a public method on the new class.
- 🔧 Avoid coupling tests to internal structure — that breaks tests on every refactor.

### 🔧 Test structure: Arrange–Act–Assert (a.k.a. Given–When–Then)
1. **Arrange / Given** — set up test data.
2. **Act / When** — call the method under test.
3. **Assert / Then** — check the result.
- 🔧 Test **one condition per test**.

### Framework helpers
- 🔧 Most frameworks ship test helpers — read your framework's docs.
- Spring example: **MockMVC** — a DSL to test controllers without the full HTTP stack.

---

## 3. Integration Tests (middle layer)

- Test the **integration points** with external systems: databases, filesystems, network/REST services, queues.
- 🔧 Run external dependencies **locally** where you can.
- Slower than unit tests. Also exercise **serialization / deserialization** boundaries.

### Database integration (recipe)
1. 🔧 Start a database.
2. Connect the app.
3. Trigger code that **writes** data.
4. Verify by **reading** the data back.
- Example: Spring Boot uses in-memory **H2** for tests instead of production PostgreSQL.

### Integration with separate services
- 🔧 Use **Wiremock** to **stub** the external service.
  - Removes dependency on third-party uptime.
  - Avoids hitting / polluting production systems.
- Example: `WeatherClientIntegrationTest` mocks `darksky.net` on `localhost:8089`.

---

## 4. Contract Tests / Consumer-Driven Contracts (CDC)

- Test the **interface between two services** to guarantee they stay compatible.
- **CDC:** the **consumer** defines its expectations; the **provider** must keep meeting them.

### 🔧 CDC process
1. Consuming team writes automated tests defining their expectations.
2. Those tests are **published** to the providing team.
3. Provider runs the CDC tests **continuously** in its pipeline.
4. A failing CDC test = a **breaking change** → teams must talk before shipping.

- **Benefit:** autonomous teams + automatic interface verification + no surprise breakage.
- **Tool:** **Pact** (JVM, Ruby, .NET, JavaScript, …) — the prominent CDC framework.

### Three perspectives
- **Consumer test (our team):** define expectations in Pact's DSL → produces a **pact file** (JSON contract).
- **Provider test (other team):** read the pact file, verify the **real API** satisfies it (Spring Pact + MockMVC).
- **Provider test (our team is provider):** verify *we* fulfill the consuming teams' pact files.

---

## 5. UI Tests (top-ish)

- 🔧 UI tests are **not necessarily end-to-end**. You can test UI behavior in isolation.
- Three separable aspects:
  - **Behavior** (clicks, input, state changes) → unit or integration level. SPA frameworks (React/Vue/Angular) make this easy.
  - **Layout / visual** → screenshot-comparison tools: **Galen**, **lineup / jlineup** catch visual regressions.
  - **Usability / design** → **not** automatable → needs exploratory testing + user feedback.
- **Tools:** Selenium + WebDriver Protocol; `webdrivermanager` to simplify browser setup.

---

## 6. End-to-End Tests (very top — fewest)

- Test the **whole integrated system** via UI or REST API. Highest confidence, but:
  - 🔧 **Slow**, **flaky** (false positives), maintenance-heavy.
  - Break on browser quirks, timing, animations.
  - Ownership is unclear in microservices.
  - Running *all* services locally is impractical at scale.
- 🔧 **Strategy:** test only **high-value user journeys** (core product flows).
  - E-commerce example: search → add to basket → checkout.
- Examples:
  - **UI E2E:** Chrome WebDriver (Selenium) navigates and asserts UI content.
  - **REST API E2E:** **REST-assured** fires real HTTP requests at a deployed service. 🔧 Preferred when there's no web UI (like this banking API!).

---

## 7. Acceptance Tests

- Prove a feature works **from the user's perspective**, in **business language**.
- Focus on observable **behavior / outcomes**, not technical implementation.
- 🔧 Framing: **"Given [precondition], when [action], then [expected result]."**
- Tools: BDD frameworks (**Cucumber**); readable assertion libs (e.g. chai.js `should`).
- 🔧 Acceptance tests can live at **any** pyramid level — not just the top.

---

## 8. Exploratory Testing

- **Manual**, creative, destructive testing to find what automation misses (usability, design, edge cases).
- 🔧 Process:
  - Schedule regular exploratory sessions.
  - Try to **break** the app on purpose.
  - Document findings.
  - **Automate each discovered bug** as a regression test (push it down the pyramid).
- Findings also reveal gaps in your build pipeline → use them to improve it.

---

## 9. Terminology Warning

- The industry has **no standard** for test names: "integration", "component", "service" mean different things to different teams.
- 🔧 **Action:** agree on naming + scope **within your team**; be explicit. Consensus > the "correct" word.

---

## 10. Deployment Pipeline (CI/CD)

- 🔧 Order tests by **speed & scope**, not by type:
  - **Early stages:** fast unit + narrow integration tests (seconds → minutes).
  - **Later stages:** broader/slower integration + end-to-end tests.
- Goal: tell the developer they broke something **as quick as possible**.

---

## 11. Avoiding Duplication & Pushing Tests Down

- 🔧 **Rule:** *"If a higher-level test spots an error and there's no lower-level test failing, you need to write a lower-level test."*
- 🔧 **Rule:** *"Push your tests as far down the test pyramid as you can."*
- Lower-level tests: isolate errors better, run faster, make better regression tests.
- 🔧 If a high-level test only re-checks what a low-level test already covers (e.g. HTTP plumbing) → **delete it**. Redundant high-level tests cost time without adding confidence.

---

## 12. Clean Test Code

- 🔧 *"Test code is as important as production code. Give it the same level of care and attention."*
- 🔧 One condition per test; use Arrange–Act–Assert.
- 🔧 *"Readability matters. Don't try to be overly DRY. Duplication is okay, if it improves readability."*
- Balance **DRY** vs **DAMP** (Descriptive And Meaningful Phrases).
- 🔧 **Rule of Three / "use before reuse"** — don't extract/refactor until a pattern shows up ~3 times.

---

## Quick Reference Cheat Sheet

| Layer | How many | Speed | Tools mentioned | Tests what |
|-------|----------|-------|-----------------|------------|
| Unit | Lots | Fast | JUnit, Mockito | A unit's public behavior, isolated |
| Integration | Some | Medium | Wiremock, H2 | DB / external service boundaries |
| Contract (CDC) | Per interface | Medium | Pact | Service-to-service compatibility |
| UI | Few | Medium | Selenium, jlineup, Galen | UI behavior / layout |
| End-to-End | Very few | Slow/flaky | Selenium, REST-assured | Critical user journeys, whole system |
| Exploratory | Manual sessions | — | (human) | What automation can't catch |

### The rules, in one place
1. Write **lots of** small/fast tests, **fewer** as you go up.
2. Test **behavior**, not implementation.
3. Don't test trivial code or private methods.
4. Push tests **as far down** the pyramid as possible.
5. If a high-level test fails with no low-level failure → **add a low-level test**.
6. Delete redundant higher-level tests.
7. Treat test code like production code; favor readability over DRY.
8. Agree on test **naming** within your team.
9. Order the pipeline by **speed**, fail fast.
