PYTHON ?= python3

.PHONY: demo test check-sessions login-weibo login-xiaohongshu collect-dailyhot collect-core-details collect-aux-evidence cluster-topics generate-briefs render-report run-core-pipeline

demo:
	$(PYTHON) -m src.demo_collect_hot_topics

test:
	$(PYTHON) -m unittest discover -s tests -v

check-sessions:
	$(PYTHON) -m src.browser.session_manager check

login-weibo:
	$(PYTHON) -m src.browser.session_manager login weibo

login-xiaohongshu:
	$(PYTHON) -m src.browser.session_manager login xiaohongshu

collect-dailyhot:
	$(PYTHON) -m src.core_pipeline.run paths

collect-core-details:
	$(PYTHON) -m src.core_pipeline.run paths

collect-aux-evidence:
	$(PYTHON) -m src.core_pipeline.run paths

cluster-topics:
	$(PYTHON) -m src.core_pipeline.run paths

generate-briefs:
	$(PYTHON) -m src.core_pipeline.run paths

render-report:
	$(PYTHON) -m src.core_pipeline.run render-report

run-core-pipeline: check-sessions collect-dailyhot collect-core-details collect-aux-evidence cluster-topics generate-briefs render-report
