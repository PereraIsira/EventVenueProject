from contextlib import nullcontext
import re
import json
from uuid import UUID
import uuid
from flask import Flask, send_from_directory, request
from flask.signals import request_tearing_down
from sqlalchemy.sql.elements import Null
from sqlalchemy.sql.operators import like_op
from sqlalchemy.sql.sqltypes import JSON, String
from sqlalchemy.util.langhelpers import MemoizedSlots
from werkzeug import useragents
from flask_restful import Api
from flask_cors import CORS #comment this on deployment
from api.HelloApiHandler import HelloApiHandler
from flask_sqlalchemy import SQLAlchemy
from flask_praetorian import Praetorian, auth_required, current_user
from psycopg2.extras import DateRange, register_uuid
from datetime import datetime
from dateutil.parser import isoparse


app = Flask(__name__, static_url_path='', static_folder='frontend/build')

CORS(app) #comment this on deployment

api = Api(app)

# Configure JWT
app.config['SECRET_KEY'] = 'group8secret'
app.config['JWT_ACCES_LIFESPAN'] = {'hours': 24}
app.config['JWT_REFRESH_LIFESPAN'] = {'days': 30}
guard = Praetorian()

# Configure database
app.config['SQLALCHEMY_DATABASE_URI'] = 'postgresql+psycopg2://huggcxzybmdegm:401d28ec5d40d5a1924bf74add6adde719115f7e3276fc4a16a4c69db1aca1d0@ec2-52-207-47-210.compute-1.amazonaws.com:5432/d49i5f0i3s50ib'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

# Initialize flask-praetorian and create database
from models import Reservation, User, Venue, VenueBookmark, Wedding, WeddingBookmark
with app.app_context():
    guard.init_app(app, User)
db.create_all()


@app.route("/", defaults={'path':''})
def serve(path):
    return send_from_directory(app.static_folder,'index.html')

@app.route("/api/auth/register", methods=['POST'])
def register():
    """
    Registers a new user. 
    POST Request must contain form with "first_name", "last_name", "email", and "password" fields
    """
    if request.form["first_name"] and request.form["last_name"] and request.form["email"] and request.form["password"]:
        if db.session.query(User).filter_by(email=request.form["email"]).count() < 1:
            new_user = User(request.form["first_name"], request.form["last_name"], request.form["email"], guard.hash_password(request.form["password"]))
            db.session.add(new_user)
            db.session.commit()
            print(new_user)
            return {"message": f"User {request.form['email']}"}, 201
        else:
            return {"error": "Email already in use"}, 400
    else:
        return {"error": "Form requires first_name, last_name, email, and password."}, 400

@app.route("/api/auth/login", methods=['POST'])
def login():
    """
    Returns the JWT token if the given user is authenticated.
    Requires "email" and "password" fields in POST request.
    """
    if request.form["email"] and request.form["password"]:
        user = guard.authenticate(request.form["email"], request.form["password"])
        ret = {'access_token': guard.encode_jwt_token(user)}
        return ret, 200
    else:
        return {"error": "Request must contain email and password"}, 400

@app.route("/api/myprofile", methods=['GET'])
@auth_required
def myprofile():
    """
    Returns the logged-in user's information
    """
    user = db.session.query(User).filter_by(email=current_user().username).one_or_none()
    return {"email":user.email, "first_name": user.first_name, "last_name":user.last_name}, 200

@app.route("/api/postvenue", methods=['POST'])
@auth_required
def postvenue():
    """
    Posts Venue to Platform
    Post requiest requires "name", "description", "street_address", "city", "state", "zipcode", "pictures" 
    """
    if request.form["name"] and request.form["description"] and request.form["street_address"] and request.form["city"] and request.form["state"] and request.form["zipcode"]:
        if db.session.query(Venue).filter_by(name=request.form["name"], street_address=request.form["street_address"], zipcode=request.form["zipcode"]).count() < 1:
            if request.form["pictures"]:
                new_Venue = Venue(current_user().id,request.form["name"],request.form["description"], request.form["street_address"], request.form["city"], request.form["state"], request.form["zipcode"], request.form["pictures"])
                db.session.add(new_Venue)
                db.session.commit()
                return {"message": f"Venue {request.form['name']} with no picutures"}, 201
            else:
                new_Venue = Venue(current_user().id,request.form["name"],request.form["description"], request.form["street_address"], request.form["city"], request.form["state"], request.form["zipcode"], Null)
                db.session.add(new_Venue)
                db.session.commit()
                return {"message": f"Venue {request.form['name']}"}, 201
        else:
            return {"error": "Venue already exists"}, 400
    else:
        return {"error": "Form requires name, description, street_address, city, state, zipcode, pictures."}, 400

@app.route("/api/venue/<vid>", methods=['GET'])
@auth_required
def getvenue(vid):
    """
    Given a venue id as a path argument, returns all information on that venue
    """
    venue = db.session.query(Venue).filter_by(vid=vid).one_or_none()
    if venue is None:
        return {"error": f"Venue {vid} does not exist"}, 404
    return {"venue" : venue.serialize()}, 200

def create_reservation(start_date:str, end_date:str, venue_id:UUID, user_id:UUID) -> bool:
    """
    Reserves a venue for a given date range if it is available
    Returns true on success, returns false otherwise
    """
    # Must call before working with UUIDs in sqlachemy
    register_uuid()

    start_date = isoparse(start_date)
    end_date = isoparse(end_date)
    date_range = DateRange(lower=start_date.date(), upper=end_date.date(), bounds='[]')
    if db.session.query(Reservation).filter(Reservation.res_dates.op("&&")(date_range)).count() > 0:
        return False
    reservation = Reservation(res_dates=date_range, res_venue=venue_id, holder=user_id)
    db.session.add(reservation)
    db.session.commit()
    return True

@app.route("/api/venue/<vid>/reserve", methods=['POST'])
@auth_required
def reserve_venue(vid):
    """
    Reserves the venue for the given daterange
    Expects start date and end_date in form, venue id in address
    Dates should be ISO-8601 date strings
    """
    if request.form["start_date"] and request.form["end_date"]:
        if create_reservation(request.form["start_date"], request.form["end_date"], uuid.UUID(vid), current_user().id):
            return {"message": "Reservation created"}, 201
        else:
            return {"error": "Timeslot unavailable"}, 400
    else:
        return {"error": "Form requires start_datetime, end_datetime, and venue_id"}, 400

@app.route("/api/venue/<vid>/reservations", methods=['GET'])
@auth_required
def get_venue_reservations(vid):
    """
    Returns the list of reservations for the given venue
    Accepts "mode" query parameter with values "all", "future", or "past"
    """
    reservations = db.session.query(Reservation).filter_by(res_venue=vid).all()
    if not request.args["mode"]:
        # return all reservations for the venue
        return {"reservations" : [res.serialize() for res in reservations]}, 200
    elif request.args["mode"] == "all":
        # return all reservations for the venue
        return {"reservations" : [res.serialize() for res in reservations]}, 200
    elif request.args["mode"] == "future":
        # return reservations whose end date is in the future
        return {"reservations" : [res.serialize() for res in reservations if res.res_dates.lower >= datetime.today().date() ]}, 200
    elif request.args["mode"] == "past":
        # return reservations whose end date has passed
        return {"reservations" : [res.serialize() for res in reservations if res.res_dates.lower < datetime.today().date() ]}, 200
    else:
        return {"error": f"{request.args['mode']} is an invalid mode"}, 400

@app.route("/api/user/reservations", methods=['GET'])
@auth_required
def get_users_reservations():
    """
    Returns the list of the given user's reservations
    Accepts "mode" query parameter with values "all", "future", or "past"
    """
    reservations = db.session.query(Reservation).filter(Reservation.holder==current_user().id).all()
    if not request.args["mode"]:
        # return all reservations for the venue
        return {"reservations" : [res.serialize() for res in reservations]}, 200
    elif request.args["mode"] == "all":
        # return all reservations for the venue
        return {"reservations" : [res.serialize() for res in reservations]}, 200
    elif request.args["mode"] == "future":
        # return reservations whose end date is in the future
        return {"reservations" : [res.serialize() for res in reservations if res.res_dates.upper >= datetime.today().date() ]}, 200
    elif request.args["mode"] == "past":
        # return reservations whose end date has passed
        return {"reservations" : [res.serialize() for res in reservations if res.res_dates.upper < datetime.today().date() ]}, 200
    else:
        return {"error": f"{request.args['mode']} is an invalid mode"}, 400

@app.route("/api/postwedding", methods=['POST'])
@auth_required
def postwedding():
    """
    Posts Wedding to Platform
    Post request requires "description", "is_public", "wedding_reservation", "wedding_datetime"
    """
    
    #TODO Create reservation instance for wedding

    if request.form["description"] and request.form["is_public"] and request.form["wedding_reservation"] and request.form["wedding_datetime"]:
        if db.session.query(Wedding).filter_by(wedding_reservation=request.form["wedding_reservation"]).count(id) == 1: 
            new_wedding = Wedding(current_user.id, request.form["description"], request.form["is_public"], request.form["wedding_reservation"], request.form["wedding_datetime"])
            db.session.add(new_wedding)
            db.session.commit()
            return {"message": f"Wedding {request.form['description']}"}, 202
        else:
            return {"error": "reservation does not exist"}, 400
    else:
        return {"error": "Form requires description, description, is_public, wedding_reservation, wedding_datetime."}, 400

@app.route("/api/bookmarkvenue", methods=['POST'])
@auth_required
def bookmarkvenue():
    #TODO Use VID
    """
    Adds venue to user's bookmarked venues
    requires "name"
    """

        
    if request.form["name"]:
        if db.session.query(Venue).filter_by(name=request.form["name"]).first():
            if db.session.query(Venue).filter_by(name=request.form["name"]).count == 1:
                venue_id = db.session.query(Venue).filter_by(name=request.form["name"]).first()
                print(venue_id)
                new_bookmarked_venue = VenueBookmark(venue_id.vid,current_user.id)
                db.session.add(new_bookmarked_venue)
                db.session.commit()
                return {"message": "Venue bookmarked"}, 201
            else:
                venue_id = db.session.query(Venue).filter_by(name=request.form["name"]).first()
                db.session.query(VenueBookmark).filter_by(bookmarked_venue=venue_id.vid).delete()
                db.session.commit()
                return {"message": "Venue unbookmarked"}, 201
        else:
            return {"message": "Venue does not exist"}, 400
    else:
        return {"error": "Form Requires name"}, 400


@app.route("/api/venuesearch", methods=['GET'])
@auth_required
def venuesearch():
    """
    Returns List of Compatible Venues
    searches in "name", "description", "state", or "city"
    requires "search_terms"
    """
    if request.form["search_terms"]:
        results = db.session.query(Venue).filter(Venue.name.like("%" + request.form["search_terms"] + "%")).all()
    
        if results:
            return results, 201 
        else:
            return {"message": "No venues found"}, 400 
        
"""
        Venue.description.like("%" + request.form["search_terms"] + "%"),
        Venue.state.like("%" + request.form["search_terms"] + "%"), 
        Venue.city.like("%" + request.form["search_terms"] + "%")).all()"""

api.add_resource(HelloApiHandler, '/flask/hello')
