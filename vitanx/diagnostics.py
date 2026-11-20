"""Read-only compatibility evidence summaries; execution counts are not gameplay."""

def summarize(report):
    builds=report.get('native_builds',[])
    media=report.get('media',{})
    # Preserve raw backend counters rather than inferring gameplay from a window
    # or a successfully linked API. Physical sound and interaction need observation.
    return {
        'execution':{'status':report.get('status'),'error':report.get('error'),
                     'guest_dispatches':report.get('total_instructions',0),
                     'main_executed':report.get('main_executed',False)},
        'translation':{'regions':len(builds),'reused':sum(x.get('cache_hit') is True for x in builds)},
        'module_phases':report.get('module_phases',[]),
        'boundary':report.get('fault_context'),
        'media':media,
        'power':report.get('power'),
        'screenshot':report.get('screenshot'),
        'region_dispatch':report.get('region_dispatch'),
        'verification':{'interactive_gameplay':'unverified','physical_audio':'unverified',
                        'note':'Backend counters and guest dispatches alone do not establish gameplay.'},
    }
