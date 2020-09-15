"""Business logic server
deployed at http://heroku.travel_agent.com/api/v1/clinc/
- Get request from clinc
- Check state, add slot values, etc. Only the state and slots properties can be manipulated
- Return reponse to clinc
"""
import os
import io
import pprint
import sys
sys.path.append('./script')
from flask import Flask, render_template, request, jsonify, send_file, url_for
import requests
from api import request_clinc, FIREBASE_AUTH
from utils import get 
import firebase_admin
from firebase_admin import credentials
from firebase_admin import firestore
from business_logic_utils import capitalize_name
from itinerary_generator import ItineraryGen
import json

# estabalish filebase
cred = credentials.Certificate(FIREBASE_AUTH)
firebase_admin.initialize_app(cred)
db = firestore.client()
collection = db.collection('users')
city_collection = db.collection('city')

pp = pprint.PrettyPrinter(indent=4)


app = Flask(__name__)

@app.route("/")
def index():
    return render_template('businessLogic.html')


@app.route("/api/v1/clinc/", methods=["GET", "POST"])
def business_logic():
    """Rounter function for resolving request from Clinc."""
    clinc_request = request.json # read clinc's request.json
    print("got request from clinc...")
    pp.pprint(clinc_request)
    user_id = clinc_request['external_user_id']
    print("user ID is...", user_id)
    curr_intent = clinc_request['state'] # extract state

    # resolve request depends on the specific state
    if (curr_intent == "add_destination"):
        return resolve_add_destination(clinc_request)
    elif (curr_intent == "clean_hello"):
        return resolve_clean_hello(clinc_request)
    elif (curr_intent == "basic_info"):
        return resolve_basic_info(clinc_request)
    elif (curr_intent == "destination_info"):
        return resolve_destination_info(clinc_request)
    elif (curr_intent == "generate_shedule"):
        return resolve_generate_schedule(clinc_request)
    elif (curr_intent == "recommendation"):
        return resolve_recommendation(clinc_request)
    elif (curr_intent == "remove_destination"):
        return resolve_remove_destination(clinc_request)
    elif (curr_intent == "clean_goodbye"):
        return resolve_clean_goodbye(clinc_request)
    else:
        print("intent out of scope")


def resolve_add_destination(clinc_request):
    """Resolve request when intent state is to add destination."""
    print("start resolve add_destination...")
    user_id = clinc_request['external_user_id']
    doc_ref = collection.document(user_id)
    doc = doc_ref.get()
    if not doc.exists:
        doc_ref.set({
            'sessionId' : user_id
        })

    city_dict = doc_ref.get().to_dict()
    if  "city" not in city_dict or "length_of_visit" not in city_dict or "number_of_people" not in city_dict:
        clinc_request['slots'] = {
            "_NOBASICINFO_": {
                "type" : "string",
                "values" : [
                    {
                        "resolved" : 1,
                        "value" : "Sorry, please provide your basic information before I can add destination. "
                    }
                ]
            }
        }
        print("finish resolving, send response back to clinc...")
        pp.pprint(clinc_request)
        return jsonify(**clinc_request)

    try:
        count = doc_ref.get().to_dict()["count"]
        city = doc_ref.get().to_dict()['city']
        ndays = doc_ref.get().to_dict()['length_of_visit']
        last_edit = doc_ref.get().to_dict()['last_edit']
    except KeyError:
        city = "-1"
        print("No count or city or ndays.")

    if clinc_request['slots']:
        destination = capitalize_name(clinc_request['slots']['_DESTINATION_']['values'][0]['tokens'])
        clinc_request['slots']['_DESTINATION_']['values'][0]['value'] = destination
        clinc_request['slots']['_DESTINATION_']['values'][0]['resolved'] = 1
    
        city_doc_ref = city_collection.document(city)
        city_recommendations = city_doc_ref.get().to_dict()["recommendations"]["results"]
        city_name_dict = city_doc_ref.get().to_dict()["name_to_index"]
        
        if destination in ["This Place", "This", "It", "There", "That"]:
            print("count", count)
            if last_edit != -1:
                destination_name = city_recommendations[last_edit]['name']
            else:
                destination_name = "nowhere"
            added_destinations = doc_ref.get().to_dict()['destinations']
            if destination_name not in added_destinations: # Add successfully
                added_destinations.append(destination_name)
                doc_ref.update({
                    'destinations' : added_destinations
                })
                nplaces = len(added_destinations)-1
                if float(nplaces)/float(ndays) >= 3:
                    clinc_request['slots']['_SUGGEST_'] = {
                        "type": "string",
                        "values": [{
                            "resolved": 1,
                            "value": "You have added " + str(nplaces) + " destinations in your " + str(ndays) + "-day trip. I think that's enough. You may go to generate itinerary."
                        }]
                    }
            else:
                clinc_request['slots']['_ADDTWICE_'] = {
                    "type": "string",
                    "values": [{
                        "resolved": 1,
                        "value": destination_name + " is already in the list. No need to add twice."
                    }]
                }

            clinc_request['slots']['_DESTINATION_']['values'][0]['value'] = destination_name

        else: # Directly add place by name
            if destination in city_name_dict: # destination exists
                print('destination in dict')
            else: # destination not in recommendation list, cannot add
                clinc_request['slots']['_DESTINATION_']['values'][0]['resolved'] = 0
            
            if clinc_request['slots']['_DESTINATION_']['values'][0]['resolved'] == 1:
                added_destinations = doc_ref.get().to_dict()['destinations']
                if destination not in  added_destinations: # and haven't been added to the list
                    added_destinations.append(destination)
                    doc_ref.update({
                        'destinations' : added_destinations
                    })
                else: # This place is already in your list. No need to add twice.
                    clinc_request['slots']['_ADDTWICE_'] = {
                        "type": "string",
                        "values": [{
                            "resolved": 1,
                            "value": destination + " is already in the list. No need to add twice."
                        }]
                    }
    print("finish resolving, send response back to clinc...")
    pp.pprint(clinc_request)
    return jsonify(**clinc_request)


def resolve_basic_info(clinc_request):
    """Resolve request when state about basic info about the user."""
    print("start resolve basic info...")
    user_id = clinc_request['external_user_id']
    doc_ref = collection.document(user_id)
    doc = doc_ref.get()
    if not doc.exists:
        doc_ref.set({
            'sessionId' : user_id
        })
    number_mapper = {"one" : "1",
                    "two" : "2",
                    "three" : "3",
                    "four" : "4",
                    "five" : "5",
                    "six" : "6",
                    "seven" : "7",
                    "eight" : "8",
                    "nine" : "9",
                    "ten" : "10"
    }

    if '_CITY_' in clinc_request['slots']:
        clinc_request['slots']['_CITY_']['values'][0]['resolved'] = 1
        city_str = clinc_request['slots']['_CITY_']['values'][0]['tokens']
        city_value = city_str.capitalize()
        city_key = city_str.capitalize()
        city_tokens = city_str.split()
        if len(city_tokens) == 2: # resolve name alias
            city_key = city_tokens[0].capitalize() + '_' + city_tokens[1].capitalize()
            city_value = city_tokens[0].capitalize() + ' ' + city_tokens[1].capitalize()
        if city_key == "New_York":
            city_key = "New_York_City"
        if city_key == "Ann_Arbor":
            city_key = "Ann_Arbor2C_Michigan"
        if city_key == "Shanghai":
            city_key = "wv__Shanghai"
        if city_key == "Beijing":
            city_key = "wv_Beijing"
        clinc_request['slots']['_CITY_']['values'][0]['value'] = city_value
        rec_idx = [-1]
        doc_ref.update({
            'city': city_value,
            'count': 0,
            'destinations' : ['dummy'],
            'last_edit' : -1,
            'rec_idx' : rec_idx
        })

        recommend = None
        # When user talks about city, get request from API
        url = 'https://www.triposo.com/api/20190906/poi.json?location_id='+city_key+'&fields=id,name,intro,images,coordinates,tag_labels&count=50&account=8FRG5L0P&token=i0reis6kqrqd7wi7nnwzhkimvrk9zh6a'
        recommend = requests.get(url).json()
        if not recommend['results']:
            clinc_request['slots']['_NORESPONSE_'] = {
                "type": "string",
                "values": [
                    {
                        "resolved": 1,
                        "value": "But currently " + city_value + " is not supported, you may choose another city. "     
                    }
                ]
            }
        else:
            city_doc_ref = city_collection.document(city_value)
            city_doc_ref.set({
                "recommendations" : recommend
            })
            name_index = {}
            for idx, r in enumerate(recommend['results']):
                name_index[r['name']] = idx
            city_doc_ref.update({
                "recommendations" : recommend
            })
            city_doc_ref.update({
                "name_to_index" : name_index
            })
    else:
        if "city" in doc_ref.get().to_dict():
            clinc_request['slots']['_CITY_'] = {
                "type": "string",
                "values": [{
                    "resolved": 1,
                    "value": doc_ref.get().to_dict()["city"]
                }]
            }

    if '_LENGTH_OF_VISIT_' in clinc_request['slots']:
        clinc_request['slots']['_LENGTH_OF_VISIT_']['values'][0]['resolved'] = 1
        length_of_visit_tokens = clinc_request['slots']['_LENGTH_OF_VISIT_']['values'][0]['tokens']
        lov = length_of_visit_tokens
        lov_tokens = length_of_visit_tokens.split()
        if length_of_visit_tokens in number_mapper:
            lov = number_mapper[length_of_visit_tokens]
        if len(lov_tokens) == 2 and lov_tokens[1] == "days":
            lov = lov_tokens[0]
        if length_of_visit_tokens in ['a week', 'one week', '1 week']:
            lov = "7"
        if length_of_visit_tokens in ['weekend']:
            lov = "2"
        try:
            a = int(lov)
            clinc_request['slots']['_LENGTH_OF_VISIT_']['values'][0]['value'] = lov
            doc_ref.update({
                'length_of_visit': lov
            })
        except:
            clinc_request['slots']['_LENGTH_OF_VISIT_']['values'][0]['resolved'] = -1
    else:
        if "length_of_visit" in doc_ref.get().to_dict():
            clinc_request['slots']['_LENGTH_OF_VISIT_'] = {
                "type": "string",
                "values": [{
                    "resolved": 1,
                    "value": doc_ref.get().to_dict()["length_of_visit"]
                }]
            }

    if '_NUMBER_OF_PEOPLE_' in clinc_request['slots']:
        clinc_request['slots']['_NUMBER_OF_PEOPLE_']['values'][0]['resolved'] = 1
        number_of_people_str = clinc_request['slots']['_NUMBER_OF_PEOPLE_']['values'][0]['tokens']
        try:
            print("enter try")
            clinc_request['slots']['_NUMBER_OF_PEOPLE_']['values'][0]['value'] = str(int(number_of_people_str))
        except:
            print("enter except")
            people_number = 1
            number_of_people_tokens = number_of_people_str.split()
            for t in number_of_people_tokens:
                if t in ['with', 'and', 'take', 'parents', 'grandparents', ',']:
                    people_number += 1
                try:
                    if t in number_mapper:
                        t = number_mapper[t]
                    people_number += int(t)-1
                except:
                    pass
            clinc_request['slots']['_NUMBER_OF_PEOPLE_']['values'][0]['value'] = str(people_number)
        doc_ref.update({
            'number_of_people': clinc_request['slots']['_NUMBER_OF_PEOPLE_']['values'][0]['value']
        })
    else:
        if "number_of_people" in doc_ref.get().to_dict():
            clinc_request['slots']['_NUMBER_OF_PEOPLE_'] = {
                "type": "string",
                "values": [{
                    "resolved": 1,
                    "value": doc_ref.get().to_dict()["number_of_people"]
                }]
            }

    print("finish resolving, send response back to clinc...")
    pp.pprint(clinc_request)
    return jsonify(**clinc_request)


def resolve_clean_hello(clinc_request):
    """Resolve request when state is to clean hello."""
    print("start resolve clean hello...")
    print("finish resolving, sned response back to clinc...")
    pp.pprint(clinc_request)
    return jsonify(**clinc_request)

def resolve_clean_goodbye(clinc_request):
    """Resolve request when state is to clean goodbye."""
    print("start resolve clean goodbye...")
    print("finish resolving, sned response back to clinc...")
    pp.pprint(clinc_request)
    return jsonify(**clinc_request)


def resolve_destination_info(clinc_request):
    """Resolve request when state is about destination info."""
    print("start resolve destination_info...")
    user_id = clinc_request['external_user_id']
    doc_ref = collection.document(user_id)
    doc = doc_ref.get()
    if not doc.exists:
        doc_ref.set({
            'sessionId' : user_id
        })
    city_dict = doc_ref.get().to_dict()

    if  "city" not in city_dict:
        clinc_request['slots'] = {
            "_NOCITY_": {
                "type" : "string",
                "values" : [
                    {
                        "resolved" : 1,
                        "value" : "Sorry, please tell me which city you're going to before I can give you information. "
                    }
                ]
            }
        }
        pp.pprint(clinc_request)
        return jsonify(**clinc_request)
    try:
        city = doc_ref.get().to_dict()['city']
    except KeyError:
        city = "-1"
        print("No city.")

    if clinc_request['slots']:
        destination = capitalize_name(clinc_request['slots']['_DESTINATION_']['values'][0]['tokens'])
        city_doc_ref = city_collection.document(city)
        city_recommendations = city_doc_ref.get().to_dict()["recommendations"]["results"]
        city_name_dict = city_doc_ref.get().to_dict()["name_to_index"]

        mapper_values = {}
        existing = {}
        candidates = []
        for place in city_recommendations:
            if place['name'] in existing:
                print("*******Duplicate")
            else:
                existing[place['name']] = 1
                mapper_values[place['name']] = [place['name']]
                candidate_value = {'value' : place['name']}
                candidates.append(candidate_value)

        clinc_request['slots']['_DESTINATION_']['candidates'] = candidates
        print("*****candidates*********")
        print(candidates)
        clinc_request['slots']['_DESTINATION_']['mappings'] = [
            {
                "algorithm" : "partial_ratio",
                "threshold" : 0.6,
                "type" : "fuzzy",
                "values" : mapper_values
            }
        ]  

        if destination in city_name_dict: # destination exists
            print('destination in dict')
            clinc_request['slots']['_DESTINATION_']['values'][0]['value'] = destination
            clinc_request['slots']['_DESTINATION_']['values'][0]['resolved'] = 1  # why the value of 'values' is list???
            idx = city_name_dict[destination]
            doc_ref.update({
                'last_edit': idx
            })
            idx = int(idx)
            clinc_request['visual_payload'] = {
                "intro": city_recommendations[idx]['intro'],
                "image": city_recommendations[idx]['images'][0]['sizes']['medium']['url'],
                "name": city_recommendations[idx]['name']
            }            
        else:
            clinc_request['slots']['_DESTINATION_']['values'][0]['resolved'] = 0      
        if clinc_request['slots']['_DESTINATION_']['values'][0]['resolved'] == 1:
            idx = city_name_dict[destination]
            doc_ref.update({
                'last_edit': idx
            })
    print("finish resolving, send response back to clinc...")
    pp.pprint(clinc_request)
    return jsonify(**clinc_request)


def resolve_generate_schedule(clinc_request):
    """Resolve request when state is to generate schedule."""
    print("start resolve generate_schedule...")
    user_id = clinc_request['external_user_id']
    doc_ref = collection.document(user_id)
    added_destinations = doc_ref.get().to_dict()['destinations']
    city = doc_ref.get().to_dict()['city']
    city_doc_ref = city_collection.document(city)
    city_dict = city_doc_ref.get().to_dict()

    places = []
    for d in added_destinations:
        if d == 'dummy':
            continue
        index = city_dict['name_to_index'][d]
        coord = city_dict['recommendations']['results'][index]['coordinates']
        la = coord['latitude']
        lo = coord['longitude']
        places.append({
            'name' : d,
            'coordinates' : {
                'latitude' : la,
                'longitude' : lo
            }
        })
    try:
        it_gen = ItineraryGen(int(doc_ref.get().to_dict()['length_of_visit']), places)
        plan = it_gen.make()
        print('Schedule Generated:')
        schedule = []
        days = len(plan)
        for i in range(days):
            places_in_day = []
            for j in plan[i]:
                places_in_day.append(j)
            schedule.append(places_in_day)
        doc_ref.update({
            "schedule": json.dumps(schedule)
        })       
    except TypeError:
        print('length_of_visit not int')
    print("finish resolving, send response back to clinc...")
    pp.pprint(clinc_request)
    return jsonify(**clinc_request)


def resolve_recommendation(clinc_request):
    """Resolve request when state is to give recommendation."""
    print("start resolve recommendation...")
    user_id = clinc_request['external_user_id']
    doc_ref = collection.document(user_id)
    doc = doc_ref.get()
    if not doc.exists:
        doc_ref.set({
            'sessionId' : user_id
        })
    city_dict = doc_ref.get().to_dict()

    if  "city" not in city_dict or "length_of_visit" not in city_dict or "number_of_people" not in city_dict:
        clinc_request['slots'] = {
            "_NOBASICINFO_": {
                "type" : "string",
                "values" : [
                    {
                        "resolved" : 1,
                        "value" : "Sorry, please provide your basic information before I can recommend. "
                    }
                ]
            }
        }
        pp.pprint(clinc_request)
        return jsonify(**clinc_request)
    try:
        city = doc_ref.get().to_dict()['city']
        count = doc_ref.get().to_dict()['count']
    except:
        city = "-1"
        count = 0
    city_doc_ref = city_collection.document(city)
    city_recommendations = city_doc_ref.get().to_dict()["recommendations"]
    rec_idx = doc_ref.get().to_dict()['rec_idx']

    if clinc_request['slots']:
        if clinc_request['slots']['_PREFERENCE_']['values'][0]['preference_mapper'] in ['hotels', 'restaurants', 'amusement parks', 'attractions', 'museums', 'shopping centers']:
            preference = clinc_request['slots']['_PREFERENCE_']['values'][0]['preference_mapper']
            tmp_pref = preference
            if preference == "restaurants":
                preference = "cuisine"
            if preference == "attractions":
                preference = "topattractions"
            if preference == "amusement parks":
                preference = "amusementpark"
            if preference == "shopping centers":
                preference = "shopping"
            for i in range(50):
                if preference and preference in city_recommendations['results'][i]['tag_labels'] and i not in rec_idx:
                    rec_idx.append(i)
                    clinc_request['slots'] = {
                        "_RECOMMENDATION_": {
                            "type": "string",
                            "values": [
                                {
                                    "resolved": 1,
                                    "value": city_recommendations['results'][i]['name']               
                                }
                            ]
                        },
                        "_CITY_": {
                            "type" : "string",
                            "values": [
                                {
                                    "resolved" : 1,
                                    "value": city
                                }
                            ]
                        },
                        "_PREFERENCE_": {
                            "type": "string",
                            "values": [
                                {
                                    "resolved": 1,
                                    "value": tmp_pref
                                }
                            ]
                        }
                    }
                    if city_recommendations['results'][i]['images']:
                        clinc_request['visual_payload'] = {
                            "intro": city_recommendations['results'][i]['intro'],
                            "image": city_recommendations['results'][i]['images'][0]['sizes']['medium']['url'],
                            "name": city_recommendations['results'][i]['name'],
                        }
                    else:
                        clinc_request['visual_payload'] = {
                            "intro": city_recommendations['results'][i]['intro'],
                            "name": city_recommendations['results'][i]['name'],
                        }

                    doc_ref.update({
                        "last_edit": i,
                        "rec_idx" : rec_idx
                    })

                    # print("slots:", clinc_request['slots'])

                    print("finish resolving, send response back to clinc...")
                    pp.pprint(clinc_request)
                    return jsonify(**clinc_request)      
        preference = clinc_request['slots']['_PREFERENCE_']['values'][0]['tokens']
        clinc_request['slots'] = {
            "_NOPREFERENCE_": {
                "type": "string",
                "values": [
                    {
                        "resolved": 1,
                        "value": "Sorry, there's no" + preference + "i can recommend for now"
                    }
                ]
            }
        }
        return jsonify(**clinc_request)

    while "hotels" in city_recommendations['results'][count]['tag_labels'] or "cuisine" in city_recommendations['results'][count]['tag_labels'] or count in rec_idx:
        count += 1
    clinc_request['slots'] = {
        "_RECOMMENDATION_": {
            "type": "string",
            "values": [
                {
                    "resolved": 1,
                    "value": city_recommendations['results'][count]['name']               
                }
            ]
        },
        "_CITY_": {
            "type" : "string",
            "values": [
                {
                    "resolved" : 1,
                    "value": city
                }
            ]
        }
    }
 
    clinc_request['visual_payload'] = {
        "intro": city_recommendations['results'][count]['intro'],
        "image": city_recommendations['results'][count]['images'][0]['sizes']['medium']['url'],
        "name": city_recommendations['results'][count]['name'],
    }
    rec_idx.append(count)
    doc_ref.update({
        "count": count+1,
        "last_edit": count,
        "rec_idx" : rec_idx
    })
    print("finish resolving, send response back to clinc...")
    pp.pprint(clinc_request)
    return jsonify(**clinc_request)


def resolve_remove_destination(clinc_request):
    """Resolve request when state is to remove destination."""
    print("start resolve remove_destination...")
    user_id = clinc_request['external_user_id']
    doc_ref = collection.document(user_id)
    doc = doc_ref.get()
    if not doc.exists:
        doc_ref.set({
            'sessionId' : user_id
        }) 
    try:
        city = doc_ref.get().to_dict()['city']
    except:
        city = "-1"
    if clinc_request['slots']:
        destination = capitalize_name(clinc_request['slots']['_DESTINATION_']['values'][0]['tokens'])
        last_edit = doc_ref.get().to_dict()['last_edit']
        city_doc_ref = city_collection.document(city)
        city_recommendations = city_doc_ref.get().to_dict()['recommendations']
        clinc_request['slots']['_DESTINATION_']['values'][0]['value'] = destination
        if destination in ["This Place", "This", "It", "There", "That"]:
            if last_edit != -1:
                destination = city_recommendations['results'][last_edit]['name']
            else:
                destination = "nowhere"
        clinc_request['slots']['_DESTINATION_']['values'][0]['resolved'] = 1  # why the value of 'values' is list???
        clinc_request['slots']['_DESTINATION_']['values'][0]['value'] = destination
        added_destinations = doc_ref.get().to_dict()['destinations']
        found_place = 0
        for idx, d in enumerate(added_destinations):
            if destination == d:
                added_destinations.pop(idx)
                doc_ref.update({
                    'destinations' : added_destinations
                })
                found_place = 1
                break
        if found_place == 0:
            clinc_request['slots']['_NOTINLIST_'] = {
                "type": "string",
                "values": [{
                    "resolved": 1,
                    "value": destination + " is not in your list."
                }]
            }
    print("finish resolving, send response back to clinc...")
    pp.pprint(clinc_request)
    return jsonify(**clinc_request)


if __name__ == "__main__":
    app.run(host='0.0.0.0', port=os.environ.get('PORT', 8000), debug=True)
