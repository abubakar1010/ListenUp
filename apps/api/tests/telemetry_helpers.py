"""In-memory traces and metrics for tests (ADR 0031).

`capture()` points `listenup.platform.telemetry` at in-memory SDK providers for the
duration of a block. Call it after an app's lifespan has started: the lifespan
configures telemetry from the settings, which are off in tests.
"""

import json
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any

from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import InMemoryMetricReader
from opentelemetry.sdk.trace import ReadableSpan, TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from listenup.platform.telemetry import use_providers


@dataclass
class Captured:
    exporter: InMemorySpanExporter
    reader: InMemoryMetricReader

    def spans(self) -> list[ReadableSpan]:
        return list(self.exporter.get_finished_spans())

    def span(self, name: str) -> ReadableSpan:
        [found] = [span for span in self.spans() if span.name == name]
        return found

    def points(self, metric: str) -> list[tuple[dict[str, Any], Any]]:
        """(attributes, value) of every data point of `metric`; a histogram's value is
        its count."""
        found: list[tuple[dict[str, Any], Any]] = []
        data = self.reader.get_metrics_data()
        for resource in data.resource_metrics if data else []:
            for scope in resource.scope_metrics:
                for item in scope.metrics:
                    if item.name != metric:
                        continue
                    for point in item.data.data_points:
                        value = getattr(point, "value", None)
                        if value is None:
                            value = getattr(point, "count", None)
                        found.append((dict(point.attributes or {}), value))
        return found

    def everything(self) -> str:
        """Every span and metric as text, for checks that something never appears."""
        spans = [span.to_json() for span in self.spans()]
        data = self.reader.get_metrics_data()
        metrics = data.to_json() if data else ""
        return json.dumps({"spans": spans, "metrics": metrics})


@contextmanager
def capture() -> Iterator[Captured]:
    exporter = InMemorySpanExporter()
    tracer_provider = TracerProvider()
    tracer_provider.add_span_processor(SimpleSpanProcessor(exporter))
    reader = InMemoryMetricReader()
    use_providers(tracer_provider, MeterProvider(metric_readers=[reader]))
    try:
        yield Captured(exporter, reader)
    finally:
        use_providers()
