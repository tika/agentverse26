"""Matched first-scene GPU comparison; not a general hardware benchmark."""
from statistics import mean


def compare(rtx_report,l40s_report,rtx_runtime,l40s_runtime):
    def times(report,runtime):
        elapsed=[f['elapsed_seconds'] for f in report['frames']]
        increments=[b-a for a,b in zip(elapsed,elapsed[1:])]
        return dict(worker_seconds=runtime['worker_seconds'],build_seconds=report['build_seconds'],
                    capture_including_warmup_seconds=report['capture_and_export_seconds'],
                    mean_frame_seconds_after_first=mean(increments) if increments else None)
    if rtx_report['seed']!=l40s_report['seed'] or rtx_report['images']!=l40s_report['images']:
        raise ValueError('GPU comparison must use the same seed and frame count')
    rtx=times(rtx_report,rtx_runtime);l40=times(l40s_report,l40s_runtime)
    return dict(seed=rtx_report['seed'],images=rtx_report['images'],rtx_pro_6000=rtx,l40s=l40,
                whole_job_speedup=l40['worker_seconds']/rtx['worker_seconds'],
                after_first_frame_speedup=l40['mean_frame_seconds_after_first']/rtx['mean_frame_seconds_after_first']
                    if rtx['mean_frame_seconds_after_first'] and l40['mean_frame_seconds_after_first'] else None,
                note='One cold scene per GPU; includes CPU/driver/startup effects. A one-image run cannot measure sustained throughput. Control images excluded from release.')
