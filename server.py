"""Backend server
Resolve request from the frontend.
"""
import sys
sys.path.append('./script')
import os
import io
import json
from flask import Flask, render_template, request, jsonify, send_file, url_for
import requests
from api import request_clinc, FIREBASE_AUTH, TTS_AUTH
import pprint
from utils import get
from record import record, auto_record # record utterance query
from google.cloud import speech # Imports the Google Cloud client library
from google.cloud.speech import enums
from google.cloud.speech import types
from google.cloud import texttospeech
import firebase_admin # import database
from firebase_admin import credentials
from firebase_admin import firestore

pp = pprint.PrettyPrinter(indent=4)
os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = FIREBASE_AUTH
os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = TTS_AUTH

speech_to_text_client = speech.SpeechClient() # speech to text client
text_to_speech_client = texttospeech.TextToSpeechClient() # text to speech client

cred = credentials.Certificate(FIREBASE_AUTH)
firebase_admin.initialize_app(cred)
db = firestore.client() # db client
collection = db.collection('users')

app = Flask(__name__)


@app.route("/")
def index():
    return render_template('index.html')


@app.route("/record_to_text/", methods=["GET", "POST"])
def record_to_text():
    """Audio to text."""
    record() # record the file
    print("transcribing the audio file...")
    # call asr api to turn the blocking.wav to text
    file_name = 'blocking.wav' # name of the audio file to transcribe
    # Loads the audio into memory
    with io.open(file_name, 'rb') as audio_file:
        content = audio_file.read()
        audio = types.RecognitionAudio(content=content)
    config = types.RecognitionConfig(
        encoding=enums.RecognitionConfig.AudioEncoding.LINEAR16,
        sample_rate_hertz=44100,
        language_code='en-US')
    # Detects speech in the audio file
    response = speech_to_text_client.recognize(config, audio)
    transcript = ''
    for result in response.results:
        transcript += result.alternatives[0].transcript
        print('Transcript: {}'.format(result.alternatives[0].transcript))
    data = {
        "response": transcript
    }
    return jsonify(**data)


@app.route('/get_audio/')
def get_audio():
    filename = 'output.mp3'
    return send_file(filename, mimetype='audio/mp3')

@app.route('/start_audio/')
def get_silence():
    filename = 'start.mp3'
    return send_file(filename, mimetype='audio/mp3')

def text_to_speech(text):
    # Set the text input to be synthesized
    synthesis_input = texttospeech.types.SynthesisInput(text=text)
    # Build the voice request, select the language code ("en-US") and the ssml
    # voice gender ("neutral")
    voice = texttospeech.types.VoiceSelectionParams(
        language_code='en-US',
        ssml_gender=texttospeech.enums.SsmlVoiceGender.NEUTRAL)
    # Select the type of audio file you want returned
    audio_config = texttospeech.types.AudioConfig(
        audio_encoding=texttospeech.enums.AudioEncoding.MP3)
    # Perform the text-to-speech request on the text input with the selected
    # voice parameters and audio file type
    response = text_to_speech_client.synthesize_speech(synthesis_input, voice, audio_config)
    # The response's audio_content is binary.
    with open('output.mp3', 'wb') as out:
        # Write the response to the output file.
        out.write(response.audio_content)
        print('Audio content written to file "output.mp3"')


@app.route("/query_clinc/", methods=["GET", "POST"])
def resolve_user_query():
    """Resolve user query from frontend to Clinc."""
    # get query from the front end
    query = request.json['query'] 
    user_id = request.json['userId']
    print("got query from front end...")
    print(query)
    print("got user ID from front end...")
    print(user_id)
    # request clinc and get response, (if that competency has its business logic enabled)
    print("got response from clinc...")
    response = request_clinc(query, user_id)
    pp.pprint(response)
    # if dest_info, slot mapper, request again
    print("*****", get(response, '', 'bl_resp', 'intent'), "*******")
    if (get(response, '', 'bl_resp', 'intent') == "destination_info_start"):
        print("*********enter*************")
        dest = get(response, '', 'slots', '_DESTINATION_', 'values', 0, 'value')
        print("-->dest is", dest)
        query = "Do you know " + dest
        response = request_clinc(query, user_id)
    
    result = get(response, 'no speakableResponse from clinc', 'visuals', 'speakableResponse')
    data = {
        'response': result,
        'destinations': get_destinations(user_id), # current list of destinations added by the user
        'isRecommendation': False if get(response, False, 'visuals', 'intro') == False else True, 
        'intro': get(response, '', 'visuals', 'intro'), # intro about the destination
        'img': get(response, '', 'visuals', 'image'), # an exrernal image url for the destination 
        # 'dest': get(response, '', 'bl_resp', 'slots', '_RECOMMENDATION_', 'values', 0, 'value'),
        'dest': get(response, '', 'visuals', 'name'),
        'addVisitor': get(response, False, 'slots', '_NUMBER_OF_PEOPLE_'),
        'visitor': get(response, '', 'slots', '_NUMBER_OF_PEOPLE_', 'values', 0, 'value'),
        'addLength': get(response, False, 'slots', '_LENGTH_OF_VISIT_'),
        'length': get(response, '', 'slots', '_LENGTH_OF_VISIT_', 'values', 0, 'value'),
        'addCity': get(response, False, 'slots', '_CITY_'),
        'city': get(response, '', 'slots', '_CITY_', 'values', 0, 'value'),
        'schedule': get_coords(user_id),
    }
    if get(response,'', 'bl_resp', 'state') == "destination_info":
        data["dest"] = get(response, '','bl_resp','visual_payload', 'name')
    print("got speakable response from clinc...")
    print(result)
    text_to_speech(result)
    return jsonify(**data)


@app.route("/add_destination/", methods=["GET", "POST"])
def add_distination():
    """Add destination to database by clicking the add button on UI."""
    user_id = request.json["user_id"]
    print(user_id)
    if request.method == "POST":
        destination = request.json["destination"]
        # print(destination)
        doc_ref = collection.document(user_id)
        destinations = doc_ref.get().to_dict()["destinations"]
        if destination not in destinations:
            destinations.append(destination)
            doc_ref.update({
                "destinations": destinations
            })
        # print(destinations)
        # print(doc_ref.get().to_dict()["destinations"])

    data = {
        'destinations': get_destinations(user_id),
    }
    return jsonify(**data)


def get_destinations(user_id):
    """Get destinations list of from db; returns: a list of destinations."""
    doc_ref = collection.document(user_id)
    try:
        destinations = doc_ref.get().to_dict()["destinations"]
        if destinations[0] == 'dummy':
            destinations = destinations[1:]
    except:
        destinations = []
        print("no destinations for now...")
    print("fetch destinations list from database...")
    print(destinations)
    return destinations


def get_coords(user_id):
    doc_ref = collection.document(user_id)
    try:
        coords = doc_ref.get().to_dict()["schedule"]
        schedule = json.loads(coords)
    except:
        schedule = []
        print("no schedule for now...")
    print("fetch schedule list from database...")
    print(schedule)
    return schedule


all_states = [
    "add_destination", "basic_info", "clean_goodbye", "clean_hello",
    "destination_info", "generate_shedule", "recommendation", "remove_destination", "clean_goodbye"]

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=os.environ.get('PORT', 3000), debug=True)
