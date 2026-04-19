import re

with open("app/templates/view_project.html", "r") as f:
    text = f.read()

# 1. Inject the AI Suggestions HTML right before the <template x-if="!subcontrol.evidence..." in the drawer
html_target = """												<template x-if="!subcontrol.evidence || subcontrol.evidence.length === 0">"""
html_injection = """												<!-- AI Suggestions Block -->
												<template x-if="subcontrol.ai_suggestions && subcontrol.ai_suggestions.filter(s => s.status === 'pending').length > 0">
													<div class="mb-4">
														<h5 class="text-xs font-semibold text-purple-400 mb-2 flex items-center gap-1"><i class="ti ti-robot"></i> Pending AI Suggestions</h5>
														<template x-for="sugg in subcontrol.ai_suggestions.filter(s => s.status === 'pending')" :key="sugg.id">
															<div class="p-3 bg-purple-500/10 border border-purple-500/20 rounded-lg mb-2">
																<p class="text-sm text-gray-200 mb-1" x-text="sugg.payload.suggestion_text"></p>
																<p class="text-xs text-gray-400 italic mb-3" x-text="sugg.payload.rationale"></p>
																<div class="flex gap-2">
																	<button @click="handleAiSuggestion(subcontrol.id, sugg.id, 'accept', subcontrol)" class="btn btn-xs btn-success !px-3">Accept</button>
																	<button @click="handleAiSuggestion(subcontrol.id, sugg.id, 'dismiss', subcontrol)" class="btn btn-xs btn-ghost text-red-400 hover:text-red-300 !px-3">Dismiss</button>
																</div>
															</div>
														</template>
													</div>
												</template>
"""
if html_target in text:
    text = text.replace(html_target, html_injection + html_target)
    print("Injected HTML")
else:
    print("Could not find HTML target")

# 2. Inject the JS method in projectData()
js_target = """		fetchProjectData() {"""
js_injection = """		handleAiSuggestion(subcontrolId, suggestionId, action, subcontrolObj) {
			fetch(`/api/v1/projects/${this.projectId}/subcontrols/${subcontrolId}/suggestions/${suggestionId}`, {
				method: 'PUT',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({ action: action })
			}).then(res => res.json()).then(data => {
				let sugg = subcontrolObj.ai_suggestions.find(s => s.id === suggestionId);
				if (sugg) sugg.status = action;
				if (action === 'accept') {
					this.notify("AI Suggestion matched and integrated.", "success");
					this.loadProjectSubcontrol(subcontrolId); // refresh notes 
				} else {
					this.notify("AI Suggestion dismissed.", "info");
				}
			});
		},

"""
if js_target in text:
    text = text.replace(js_target, js_injection + js_target)
    print("Injected JS")
else:
    print("Could not find JS target")

with open("app/templates/view_project.html", "w") as f:
    f.write(text)
print("Done patching UI")
