from xml.dom.minidom import parse
from datetime import datetime, timedelta
from math import sqrt
import googlemaps
import pprint
import math

input_filename = '/home/sk/gpx-fixer/original.gpx'
output_filename = '/home/sk/gpx-fixer/filled.gpx'

time_gap = 600 # seconds


DATE_FORMAT = "%Y-%m-%dT%H:%M:%SZ"

dom = parse(input_filename)

gmaps = googlemaps.Client(key='AIzaSyDYS1ePTz4lPheEeifG8cli-w84TGis8X4')

class GpxPoint:
    def __init__(self, lat, lng, time, elevation):
        self.lat = lat
        self.lng = lng
        self.time = time
        self.elevation = elevation

    def coordString(self):
        return "%f,%f" % (self.lat, self.lng)

    def toDomNode(self, dom):
        pointNode = dom.createElement("trkpt")
        pointNode.setAttribute("lat", str(self.lat))
        pointNode.setAttribute("lon", str(self.lng))
        timeNode = dom.createElement("time")
        timeNode.appendChild(dom.createTextNode(self.time.strftime(DATE_FORMAT)))
        pointNode.appendChild(timeNode)
        elevationNode = dom.createElement("ele")
        elevationNode.appendChild(dom.createTextNode(str(self.elevation)))
        pointNode.appendChild(elevationNode)
        return pointNode

def handleGpx(gpx):
    handleTrack(gpx.getElementsByTagName("trk")[0])

def handleTrack(trk):
    handleTrackSegment(trk.getElementsByTagName("trkseg")[0])

def handleTrackSegment(trkseg):
    handleTrackPoints(trkseg.getElementsByTagName("trkpt"))

def handleTrackPoints(points):

    # pseudo code:
    # - find two points > X seconds apart
    # - query a route between the two points using GMaps API
    # - distance / X seconds gives the distance each point should travel
    # - decode polyline using http://seewah.blogspot.co.uk/2009/11/gpolyline-decoding-in-python.html
    # - travel the path of the polyline tracking distance travelled until we go past next point's distance
    # - calculate that points location between on straight line between last two polyline coordinates

    last_point = parsePoint(points[0])
    for p in points[1:]:
        cur_point = parsePoint(p)
        gap = (cur_point.time - last_point.time).total_seconds()
        if gap > time_gap:
            print "Filling time gap of %d seconds at %s" % (gap, str(last_point))
            new_points = generatePointsBetween(last_point, cur_point)
            print "Generated %d points" % (len(new_points))
            parent_node = p.parentNode
            for np in new_points:
                parent_node.insertBefore(np.toDomNode(dom), p)
		print "Inserted a point"
            print "Inserted %d points" % (len(new_points))

        last_point = cur_point

def decodeLine(encoded):

    """Decodes a polyline that was encoded using the Google Maps method.

    See http://code.google.com/apis/maps/documentation/polylinealgorithm.html

    This is a straightforward Python port of Mark McClure's JavaScript polyline decoder
    (http://facstaff.unca.edu/mcmcclur/GoogleMaps/EncodePolyline/decode.js)
    and Peter Chng's PHP polyline decode
    (http://unitstep.net/blog/2008/08/02/decoding-google-maps-encoded-polylines-using-php/)
    """

    encoded_len = len(encoded)
    index = 0
    array = []
    lat = 0
    lng = 0

    while index < encoded_len:

        b = 0
        shift = 0
        result = 0

        while True:
            b = ord(encoded[index]) - 63
            index = index + 1
            result |= (b & 0x1f) << shift
            shift += 5
            if b < 0x20:
                break

        dlat = ~(result >> 1) if result & 1 else result >> 1
        lat += dlat

        shift = 0
        result = 0

        while True:
            b = ord(encoded[index]) - 63
            index = index + 1
            result |= (b & 0x1f) << shift
            shift += 5
            if b < 0x20:
                break

        dlng = ~(result >> 1) if result & 1 else result >> 1
        lng += dlng

        array.append((lat * 1e-5, lng * 1e-5))

    return array

def getCoordList(leg):
    steps = leg["steps"]
    # extract coords for each step
    steps_coords = map(lambda s: decodeLine(s["polyline"]["points"]), steps)
    # join coords together, dropping the duplicate at start of next step
    return reduce(lambda coords1,coords2: coords1 + coords2[1:], steps_coords)

def getDirectionCoordsBetween(startPoint, endPoint):
    directions_result = gmaps.directions(startPoint.coordString(),
                                         endPoint.coordString(),
                                         mode="driving")
    if directions_result:
        route = directions_result[0]
        leg = route["legs"][0]

        return getCoordList(leg)
    else:
        return []

def distBetween((lat1, lng1), (lat2, lng2)):
    earth_radius = 6371009.0 # metres
    d_lat = math.radians(lat2-lat1)
    d_lng = math.radians(lng2-lng1)
    sind_lat = math.sin(d_lat / 2)
    sind_lng = math.sin(d_lng / 2)
    a = math.pow(sind_lat, 2) + math.pow(sind_lng, 2) * math.cos(math.radians(lat1)) * math.cos(math.radians(lat2));
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1.0-a))
    return earth_radius * c

def getAccumulatedDistances(coords):
    distances = [0.0]
    for i in range(0, len(coords)-2):
        distances.append(distances[-1] + distBetween(coords[i], coords[i+1]))
    return distances

def advance(req_distance, idx, distances):
    while distances[idx+1] < req_distance:
        idx += 1
    return idx

def interpolate_coords((x0, y0), (x1, y1), ratio):
    x_dist = x1 - x0
    y_dist = y1 - y0
    return x0 + x_dist*ratio, y0 + y_dist*ratio


def chunks(l, n):
    """Yield successive n-sized chunks from l."""
    for i in xrange(0, len(l), n):
        yield l[i:i+n]

def getElevations(coords):
    elevations = []
    for coord_chunk in chunks(coords, 50):
        elevation_response = gmaps.elevation(coord_chunk)
        elevations.extend(map(lambda e: e["elevation"], elevation_response ))
    return elevations

def generatePointsBetween(startPoint, endPoint):

    coords = getDirectionCoordsBetween(startPoint, endPoint)

    acc_distances = getAccumulatedDistances(coords)
    total_distance = acc_distances[-1]

    total_seconds = int((endPoint.time - startPoint.time).total_seconds())

    second_intervals = range(0, total_seconds)


    idx = 0
    final_coords = []
    for s in second_intervals:
        required_distance = float(s) / total_seconds * total_distance
        idx = advance(required_distance, idx, acc_distances)
        coord_ratio = (required_distance - acc_distances[idx]) / (acc_distances[idx+1] - acc_distances[idx])

        final_coords.append(interpolate_coords(coords[idx], coords[idx+1], coord_ratio))

    elevations = getElevations(final_coords)

    return map(lambda coord, seconds, elevation: GpxPoint(coord[0], coord[1], startPoint.time + timedelta(seconds=seconds), elevation), final_coords, second_intervals, elevations)

def getTimeAsDateTime(point):
    return datetime.strptime(point.getElementsByTagName("time")[0].firstChild.data, DATE_FORMAT)

def calculateTotalDistance(points):
    last_coord = parseCoordinates(points[0])
    dist = 0.0
    for point in points[1:]:
        coord = parseCoordinates(point)
        dist += distance(last_coord, coord)
        last_coord = coord
    return dist

def parsePoint(point):
    return GpxPoint(
        float(point.getAttribute("lat")), 
        float(point.getAttribute("lon")), 
        getTimeAsDateTime(point), 
        float(point.getElementsByTagName("ele")[0].firstChild.data))

def distance(frm, to):
    lat_dist = to[0] - frm[0]
    long_dist = to[1] - frm[1]
    return sqrt(lat_dist*lat_dist + long_dist*long_dist)

handleGpx(dom)

dom.writexml(open(output_filename, 'w'), indent="  ", addindent="  ", newl="\n")
 
dom.unlink()


