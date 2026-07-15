class OfflineCommercialProvider {
  id() {
    return "tame-ink:commercial-fixture";
  }

  async callApi(_prompt, context) {
    if (!context?.vars?.fixtureReport) {
      return { error: "fixtureReport is required" };
    }
    return { output: JSON.stringify(context.vars.fixtureReport) };
  }
}

module.exports = OfflineCommercialProvider;
