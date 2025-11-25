// javascript
import React, { useState, useEffect, useCallback } from "react";
import api from "./api.js"
import "./App.css"; // We'll add some styles for the modal here

function App() {

  const empty_event = {
    summary: "",
    start_time: "",
    end_time: "",
    earliest_start: "",
    latest_end: "",
    is_flexible: false,
    duration_minutes: 0,
    google_id: "",
  };

  const [events, setEvents] = useState([]);
  const [formData, setFormData] = useState(empty_event);
  const [showModal, setShowModal] = useState(false);


  const fetchEvents = useCallback(async () => {
    try {
      const response = await api.get("/events");
      setEvents(response.data.events);
    } catch (error) {
      console.error("Error fetching events:", error);
    }
  }, []);

  useEffect(() => {
    fetchEvents();
    const intervalId = setInterval(fetchEvents, 30000); // 30,000 ms = 30s
    return () => clearInterval(intervalId);
  }, [fetchEvents]);

  // Generic handler that supports checkboxes and numbers
  const handleChange = (e) => {
    const { name, value, type, checked } = e.target;
    const newVal = type === "checkbox" ? checked : (type === "number" ? (value === "" ? "" : Number(value)) : value);
    setFormData({ ...formData, [name]: newVal });
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    console.log('submitting data');
    try {
      if (formData.google_id) {
        // Edit event
        console.log(formData);
        await api.put(`/events/${formData.google_id}`, formData);
      } else {
        // Create event
        console.log(formData);
        await api.post("/events", formData);
      }
      fetchEvents();
      setShowModal(false);
      setFormData(empty_event);
    } catch (error) {
      console.error("Error saving event:", error);
    }
  };

  const handleDelete = async (google_id) => {
    try {
      await api.delete(`/events/${google_id}`);
      fetchEvents();
    } catch (error) {
      console.error("Error deleting event:", error);
    }
  };

  const handleEdit = (event) => {
    setFormData(event);
    setShowModal(true);
  };

  return (
    <div className="app-container">
      <h1>My Calendar</h1>
      <button className="create-button" onClick={() => { setFormData(empty_event); setShowModal(true); }}>
        Create New Event
      </button>

      {/* Event List */}
      <ul className="event-list">
        {events.map((event) => (
          <li key={event.google_id} className="event-item">
            <strong>{event.summary}</strong> | {event.start_time} - {event.end_time}{" "}
            <button onClick={() => handleEdit(event)}>Edit</button>{" "}
            <button onClick={() => handleDelete(event.google_id)}>Delete</button>
          </li>
        ))}
      </ul>

      {/* Modal Form */}
      {showModal && (
        <div className="modal-overlay">
          <div className="modal">
            <h2>{formData.google_id ? "Edit Event" : "Create Event"}</h2>
            <form onSubmit={handleSubmit}>
              <label>
                Name:
                <input
                  type="text"
                  name="summary"
                  value={formData.summary || ""}
                  onChange={handleChange}
                  required
                />
              </label>

              <label>
                Flexible:
                <input
                  type="checkbox"
                  name="is_flexible"
                  checked={!!formData.is_flexible}
                  onChange={handleChange}
                />
              </label>

              {!formData.is_flexible ? (
                <>
                  <label>
                    Start Time:
                    <input
                      type="datetime-local"
                      name="start_time"
                      value={formData.start_time || ""}
                      onChange={handleChange}
                      required
                    />
                  </label>
                  <label>
                    End Time:
                    <input
                      type="datetime-local"
                      name="end_time"
                      value={formData.end_time || ""}
                      onChange={handleChange}
                      required
                    />
                  </label>
                </>
              ) : (
                <>
                  <label>
                    Earliest Start:
                    <input
                      type="datetime-local"
                      name="earliest_start"
                      value={formData.earliest_start || ""}
                      onChange={handleChange}
                      required
                    />
                  </label>
                  <label>
                    Latest End:
                    <input
                      type="datetime-local"
                      name="latest_end"
                      value={formData.latest_end || ""}
                      onChange={handleChange}
                      required
                    />
                  </label>
                  <label>
                    Duration (minutes):
                    <input
                      type="number"
                      name="duration_minutes"
                      min="0"
                      value={formData.duration_minutes ?? 0}
                      onChange={handleChange}
                      required
                    />
                  </label>
                </>
              )}

              <div className="modal-buttons">
                <button type="submit">{formData.google_id ? "Update" : "Create"}</button>
                <button type="button" onClick={() => setShowModal(false)}>
                  Cancel
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}

export default App;