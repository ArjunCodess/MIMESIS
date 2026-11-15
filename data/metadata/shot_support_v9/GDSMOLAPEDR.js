"use strict";

//*****************************************
// GDS MOLA PEDR Web Page Code
// 
//
//*****************************************

//**** Data URLs and other constants ****
var objBaseStatusURL = 'https://oderest.rsl.wustl.edu/livegds/?query=status&source=GDSWebMOLAPEDR&o=j&jsonp';
var objBaseGlobalDataURL = 'https://oderest.rsl.wustl.edu/livegds/?query=gmolapedr&source=GDSWebMOLAPEDR&o=j&jsonp';
var objBaseFeatureClassURL = 'https://oderest.rsl.wustl.edu/live2/?query=featureclasses&source=GDSWebMOLAPEDR&odemetadb=mars&o=j&jsonp';
var objBaseFeatureNameURL = 'https://oderest.rsl.wustl.edu/live2/?query=featurenames&source=GDSWebMOLAPEDR&odemetadb=mars&o=j&jsonp';
var objBaseFeatureDataURL = 'https://oderest.rsl.wustl.edu/live2/?query=featuredata&source=GDSWebMOLAPEDR&odemetadb=mars&o=j&jsonp';
var objBaseQueryURL = 'https://oderest.rsl.wustl.edu/livegds/?query=molapedr&source=GDSWebMOLAPEDR&odemetadb=mars&o=j&jsonp';
//var objBaseMapURL = 'https://odegismarsa.rsl.wustl.edu/arcgis/rest/services/mars_c0/mars_bm_mgs_MOLA_c0/MapServer'
var objBaseMapURL = 'https://bm1ms.rsl.wustl.edu/arcgis/rest/services/mars_c0/mars_bm_mgs_MOLA_c0/MapServer';
var objBaseMapSpatialReference = 204040;
var objBaseMapInitialZoom = 0;
var objChannels = []; //Set number of channels
var objDetectors = []; //Set number of detectors
var objQueryType = "MOLAPEDR"; //Set the query type (valid are LOLARDR, MOLAPEDR, DLRERDR)
var objMaxEstObservationsPerAsyncQuery = 150000000;
var objIncludeLTODInMaxExt = false;
var objIncludeChannelInMaxExt = false;
var objMaxObsFilterNote = "excluding product id, altitude, and time filters";
var objMaxObsReduceNote = "Please reduce query area or orbit range.";
var objDefaultMaxObservations = 595000000;
var objEstimatedObservationLatRange = 180.0;
var objEstimatedObservationLonRange = 360.0;
var objAltitudeUnits = "m";
var objTitleString = "MOLA PEDR";
var objMustHaveShapefileFormat = true;
var objMustHaveShapefileRecords = true;
//Initial Values
var objLimitProductId = false;
var objProductId = "";
var objLimitAlt = false;
var objMinAlt = 0.0;
var objMaxAlt = 0.0;
var objLimitOrbit = false;
var objMinOrbit = 0.0;
var objMaxOrbit = 0.0;
var objLimitUTC = false;
var objMinUTC = "";
var objMaxUTC = "";
var objLimitLTOD = false;
var objMinLTOD = 0.0;
var objMaxLTOD = 24.0;
var objLimitChannels = false;
var objLimitDetectors = false;
var objLimitEmAngle = false;
var objMinEmAngle = 0.0;
var objMaxEmAngle = 90.0;
var objLimitSolIn = false;
var objMinSolIn = 0.0;
var objMaxSolIn = 180.0;
var objLimitSolAz = false;
var objMinSolAz = 0.0;
var objMaxSolAz = 360.0;
var objLimitCalQual = false;
var objMinCalQual = 0;
var objMaxCalQual = 255;
var objLimitGeoQual = false;
var objMinGeoQual = 0;
var objMaxGeoQual = 255;
var objLimitMisQual = false;
var objMinMisQual = 0;
var objMaxMisQual = 255;
var objExactCountOnly = false;
var objEmailAddress = "";
var objCSVValue = true;
var objASCIIValue = false;
var objCSVFPRValue = false;
var objCSVPPR2Value = true;
var objCSVTPR3Value = false;
var objCSVSTPR4Value = false;
var objShapefileOutputValue = false;
var objShapefileOutputValue_Format_P = true;
var objShapefileOutputValue_Format_Z = false;
var objShapefileOutputValue_Records_F = true;
var objShapefileOutputValue_Records_M = false;
var objImageWidth = 600;
var objImageHeight = 600;
var objPNGFormatValue = false;
var objJPEGFormatValue = true;
var objJP2FormatValue = false;
var objGTIFFFormatValue = false;
var objKMZFormatValue = false;
var objENVIFormatValue = false;
var objGlobalColorValue = false;
var objLocalColorValue = true;
var objGlobalMonoValue = false;
var objLocalMonoValue = false;
var objBinnedImageValue = false;
var objZipOutputValue = false;
var objZipOnlyValue = true;
var objTileValue = false;
var objTileSizeValue = 5.0;
//**** End Data URLs and other constants ****