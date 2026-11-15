"""Publish the calibration decision and figures from retained measurements."""
from pathlib import Path
import hashlib
import json
import shutil
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.colors import ListedColormap, LightSource
from matplotlib.patches import Circle, Patch
import numpy as np
import rasterio
from rasterio.windows import from_bounds
from scipy.ndimage import minimum_filter

ROOT = Path(__file__).resolve().parents[1]
REPORTS = ROOT / 'artifacts/reports/discovery_v10'
PUBLIC = ROOT / 'apps/web/public/research'
GENERATED = ROOT / 'apps/web/src/generated'
PAPER = ROOT / 'artifacts/paper'
GENERATED.mkdir(exist_ok=True)
config_path = ROOT / 'configs/pit_calibration_audit_v10.json'
config = json.loads(config_path.read_text())
audit_path = REPORTS / 'calibration_audit_v10.json'
audit = json.loads(audit_path.read_text())
if audit['protocol_sha256'] != hashlib.file_digest(config_path.open('rb'),'sha256').hexdigest():
    raise ValueError('Calibration configuration changed after measurements')
if audit['decision'] != 'stop_current_pilot_before_selection':
    raise ValueError('Publication narrative must be reviewed for a changed calibration decision')
plt.rcParams.update({'font.size':10,'axes.spines.top':False,'axes.spines.right':False,'savefig.facecolor':'#f9f7f0'})
cases = []
for case in config['cases']:
    record = json.loads((ROOT / case['source_record']).read_text())
    measurements = [row for row in record['measurements'] if not row['include_manually_edited_class_15']]
    with rasterio.open(ROOT / case['terrain']) as terrain, rasterio.open(ROOT / case['confidence']) as confidence:
        cx,cy = record['source_grid_center_m']
        window = from_bounds(cx-600,cy-600,cx+600,cy+600,terrain.transform).round_offsets().round_lengths()
        z = terrain.read(1,window=window,masked=True)
        classes = confidence.read(1,window=window)
        affine = terrain.window_transform(window)
        rows,cols = np.indices(z.shape)
        x = affine.c+(cols+.5)*affine.a-cx
        y = affine.f+(rows+.5)*affine.e-cy
        diameter = record['proxy_diameter_m']
        r = np.hypot(x,y)
        annulus = (r >= diameter/2) & (r <= 2*diameter)
        quality = ~np.ma.getmaskarray(z) & np.isin(classes,config['primary_quality_classes'])
        native = np.ma.masked_where(~annulus,quality.astype(int))
        image_names = []
        for measurement in measurements:
            sigma = measurement['support_m']/terrain.res[0]
            radius = int(np.ceil(3*sigma))+1
            usable = minimum_filter(quality,size=2*radius+1,mode='constant',cval=0)
            measured_fraction = float((usable & annulus).sum()/annulus.sum())
            if abs(measured_fraction-measurement['valid_fraction']) > 1e-12:
                raise AssertionError('Figure mask disagrees with saved measurement')
            fig,axes = plt.subplots(1,2,figsize=(10,4.6),layout='constrained')
            extent = [float(x.min()-terrain.res[0]/2),float(x.max()+terrain.res[0]/2),float(y.min()-terrain.res[0]/2),float(y.max()+terrain.res[0]/2)]
            for ax,data,title in zip(axes,[native,np.ma.masked_where(~annulus,usable.astype(int))],['Native successful correlations',f'After {measurement["support_m"]} m support mask']):
                ax.set_facecolor('#edece3')
                ax.imshow(data,cmap=ListedColormap(['#b45638','#536e54']),vmin=0,vmax=1,interpolation='nearest',extent=extent,origin='upper')
                ax.add_patch(Circle((0,0),diameter/2,fill=False,color='#28372e',lw=.8))
                ax.add_patch(Circle((0,0),diameter*2,fill=False,color='#28372e',lw=.8))
                limit=2.15*diameter
                ax.set(xlim=(-limit,limit),ylim=(-limit,limit),xlabel='East of atlas center (m)',ylabel='North of atlas center (m)',title=title)
                ax.set_aspect('equal')
            fig.legend(handles=[Patch(color='#536e54',label='Usable'),Patch(color='#b45638',label='Excluded')],loc='outside lower center',ncol=2,frameon=False)
            name=f'pit-{case["id"]}-{measurement["support_m"]}m.png'
            fig.savefig(PUBLIC/name,dpi=160)
            plt.close(fig)
            mobile_name=name.replace('.png','-mobile.png')
            with plt.rc_context({'font.size':14}):
                fig,axes=plt.subplots(2,1,figsize=(5.6,10.4),layout='constrained')
                for ax,data,title in zip(axes,[native,np.ma.masked_where(~annulus,usable.astype(int))],['Native successful correlations',f'After {measurement["support_m"]} m support mask']):
                    ax.set_facecolor('#edece3')
                    ax.imshow(data,cmap=ListedColormap(['#b45638','#536e54']),vmin=0,vmax=1,interpolation='nearest',extent=extent,origin='upper')
                    for ring in [diameter/2,diameter*2]:
                        ax.add_patch(Circle((0,0),ring,fill=False,color='#28372e',lw=.8))
                    ax.set(xlim=(-limit,limit),ylim=(-limit,limit),xlabel='East of atlas center (m)',ylabel='North of atlas center (m)',title=title)
                    ax.set_aspect('equal')
                fig.legend(handles=[Patch(color='#536e54',label='Usable'),Patch(color='#b45638',label='Excluded')],loc='outside lower center',ncol=2,frameon=False)
                fig.savefig(PUBLIC/mobile_name,dpi=160)
                plt.close(fig)
            image_names.append({'support_m':measurement['support_m'],'image':name,'mobile_image':mobile_name,'valid_fraction':measured_fraction,'expected_cells':measurement['expected_cells'],'measured_cells':measurement['measured_cells']})
        posting = float(terrain.res[0])
    cases.append({'id':case['id'],'name':case['name'],'atlas_url':case['atlas_url'],'center_lat_lon':case['center_lat_lon'],
                  'proxy_diameter_m':record['proxy_diameter_m'],'pixel_m':round(posting,8),
                  'raw_valid_fraction':measurements[0]['unsmoothed_annulus_quality_fraction'],'supports':image_names})

# Standalone quantitative figure for the paper; values come from the same records.
fig,ax = plt.subplots(figsize=(9,3.8),layout='constrained')
positions=np.arange(2)
labels=['Native classes','10 m support','20 m support','40 m support']
colors=['#536e54','#777d77','#a0a49c','#c0c3b9']
for index,label in enumerate(labels):
    values=[100*(case['raw_valid_fraction'] if index==0 else case['supports'][index-1]['valid_fraction']) for case in cases]
    bars=ax.barh(positions+(index-1.5)*.18,values,height=.16,label=label,color=colors[index])
    for bar,value in zip(bars,values):
        ax.text(value+1,bar.get_y()+bar.get_height()/2,f'{value:.2f}%',va='center',fontsize=9)
ax.axvline(95,color='#b45638',ls='--',lw=1)
ax.text(94.5,1.48,'95% required',ha='right',color='#9c452f',fontsize=9)
ax.set(yticks=positions,yticklabels=['Tranquillitatis','Marius Hills'],xlim=(0,112),xlabel='Valid fraction of fixed exterior proxy (%)')
ax.invert_yaxis()
ax.legend(loc='lower right',frameon=False,ncol=2,fontsize=9)
fig.savefig(PUBLIC/'pit-support-summary.png',dpi=200)
fig.savefig(PAPER/'pit-support-summary.png',dpi=200)
plt.close(fig)

# Registered optical and terrain context. No inferred rim is drawn.
bounds=[295000,4812600,295650,4813400]
fig,axes=plt.subplots(1,2,figsize=(8,5.4),layout='constrained')
with rasterio.open(ROOT/'data/raw/discovery_v10/earth/IndianTunnel_NAIP2021_service_crop.tif') as imagery:
    axes[0].imshow(np.moveaxis(imagery.read([1,2,3]),0,-1),extent=[bounds[0],bounds[2],bounds[1],bounds[3]])
with rasterio.open(ROOT/'data/raw/discovery_v10/earth/USGS_1M_12_x29y482_ID_SouthernGaps_D23.tif') as terrain:
    z=terrain.read(1,window=from_bounds(*bounds,terrain.transform))
    shade=LightSource(315,45).hillshade(z,vert_exag=1,dx=1,dy=1)
    axes[1].imshow(shade,cmap='gray',extent=[bounds[0],bounds[2],bounds[1],bounds[3]])
for ax,title in zip(axes,['NAIP imagery, 19 June 2021','3DEP 1 m terrain, shaded']):
    ax.set(title=title,xlabel='Easting (m)',ylabel='Northing (m)')
    ax.ticklabel_format(style='plain',useOffset=False)
    ax.tick_params(axis='x',rotation=45,labelsize=8)
    ax.tick_params(axis='y',labelsize=8)
fig.savefig(PUBLIC/'pit-earth-context.png',dpi=160)
plt.close(fig)

stages=[
    {'stage':'Source feasibility','state':'partial','detail':'Earth, Moon and Mars sources acquired; exact feature packets remain unqualified.'},
    {'stage':'Calibration','state':'failed','detail':'Neither lunar calibration proxy passes at any proposed support, including all declared sensitivities.'},
    {'stage':'Freeze','state':'not_entered','detail':'The plan requires successful calibration before freezing a study.'},
    {'stage':'Search','state':'not_run','detail':'No joint or separate Earth nomination was made.'},
    {'stage':'Challenge','state':'not_run','detail':'No withheld outcomes or independent geological control results exist.'},
    {'stage':'Discovery decision','state':'no_discovery_established','detail':'The current pilot stops at source support; no new analogue is claimed.'},
    {'stage':'Communicate','state':'delivered','detail':'Measured failures, retained sources, website and paper share this decision.'}]
input_names=['calibration_audit_v10.json','lunar_calibration_proxy.json','marius_calibration_proxy.json','registered_earth_source_qa.json','registered_earth_gap_source_qa.json','caves_surface_support.json','caves_archive_inventory.json','caves_point_cloud_qa.json']
manifest={name:{'path':(REPORTS/name).relative_to(ROOT).as_posix(),'sha256':hashlib.file_digest((REPORTS/name).open('rb'),'sha256').hexdigest()} for name in input_names}
bundle={'id':'pit_study_v10','state':'stopped_at_calibration','minimum_valid_fraction':.95,'cases':cases,
        'sensitivity_runs':audit['total_sensitivity_runs'],'lunar_calibration_sites':len(cases),'analytical_controls':audit['analytical_controls'],
        'stages':stages,'nominations':[],'withheld_outcomes':[],'claim':'No Earth-Moon-Mars analogue discovery established.',
        'geometry_limit':'Atlas-based circular funnel proxies, not independently mapped rims.',
        'source_manifest':manifest,
        'source_credits':['LROC / NASA / Arizona State University','USGS 3DEP','USDA NAIP / USGS'],
        'earth_context':{'image':'pit-earth-context.png','crs':'NAD83 / UTM zone 12N','bounds':bounds,'use':'Search crop, not a nominated feature'},
        'restricted_sources':'Original CAVES point clouds and photographs are excluded from public assets.'}
serialized=json.dumps(bundle,indent=2,allow_nan=False)+'\n'
for path in [REPORTS/'pit_study_v10.json',PUBLIC/'pit_study_v10.json',GENERATED/'pit-study-v10.json']:
    path.write_text(serialized)
shutil.copy2(REPORTS/'calibration_audit_v10.json',PUBLIC/'pit-calibration-audit-v10.json')
shutil.copy2(config_path,PUBLIC/'pit-calibration-protocol-v10.json')
print('Published two lunar source cases, six mask figures, Earth context, summary figure and shared study record.')
