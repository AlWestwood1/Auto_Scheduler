import scheduler
from datetime import datetime

class RequestHandler:
    def __init__(self):
        self.db = scheduler.Database()
        self.dtc = scheduler.DateTimeConverter()
        self.em = scheduler.EventManager()
        self.optimiser = scheduler.FlexEventOptimiser()


    @staticmethod
    def _create_event_from_json(event_json: dict) -> scheduler.Event:
        #Create event object from json
        if event_json['is_flexible']:
            eb = scheduler.FlexibleEventBuilder()
            new_event = eb.create_flexible_event(event_json['earliest_start'],
                                                 event_json['latest_end'],
                                                 event_json['duration_minutes'],
                                                 event_json['summary'])

        else:
            fixed_eb = scheduler.FixedEventBuilder()
            new_event = fixed_eb.create_fixed_event(event_json['start_time'],
                                                    event_json['end_time'],
                                                    event_json['summary'])
        return new_event


    def optimise_events(self, dt):
        # Optimise flexible events for the day
        processed_events = self.optimiser.run_ILP_optimiser(dt)
        for e in processed_events:
            if scheduler.Database().event_status(e) == scheduler.EventStatus.MODIFIED:
                self.em.edit_event(e)


    def get_events(self, in_range: bool = False, from_date: str = "", to_date: str = "") -> list:
        events = None
        if in_range:
            from_dt = self.dtc.convert_str_to_dt(from_date)
            to_dt = self.dtc.convert_str_to_dt(to_date)
            #sync db with Google calendar
            self.em.sync_gc_to_db(in_range=True, start_dt=from_dt, end_dt=to_dt)
            # Fetch events from db in date range
            events = scheduler.Database().get_events_in_date_range(from_dt, to_dt)

        else:
            self.em.sync_gc_to_db()
            # Fetch all upcoming events from db
            events = scheduler.Database().get_upcoming_events()

        return [e.to_json() for e in events]


    def add_event(self, event_json: dict) -> None:
        #Create event object from json
        new_event = self._create_event_from_json(event_json)

        #Submit event
        self.em.submit_event(new_event)

        #optimise events for the day
        self.optimise_events(new_event.start_dt)


    def edit_event(self, google_id: str, updated_event_json: dict) -> None:

        #Fetch existing event from db
        existing_event = self.db.get_event_by_google_id(google_id)

        #update existing event using json data
        #if event was flexible and now isn't, or vice versa, delete and re-add

        if existing_event.is_flexible != updated_event_json['is_flexible']:
            print('deleting and adding')
            self.em.delete_event(existing_event)
            self.add_event(updated_event_json)

        else:
            print('updating')
            updated_event = self._create_event_from_json(updated_event_json)
            updated_event.google_id = google_id
            self.em.edit_event(updated_event, update_valid_window=True)

            #optimise events for the day
            self.optimise_events(updated_event.start_dt)



    def del_event(self, google_id: str) -> None:
        #Fetch existing event from db
        existing_event = self.db.get_event_by_google_id(google_id)

        self.em.delete_event(existing_event)


def main():
    print(RequestHandler().get_events(in_range=True, from_date='27-10-2025', to_date='30-10-2025'))


if __name__ == "__main__":
    main()